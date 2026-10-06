import ldap
import ldap.filter
from flask import current_app

from ..config import LDAP_TLS_OPTIONS


class LdapConfigError(Exception):
    """Raised before connecting when the LDAP settings are unusable."""


def _connect():
    """Open a connection configured from the app config.

    TLS options are set on the connection, never with the module-level
    ``ldap.set_option``: that is process-global, so one request's setting
    would leak into every later connection in the same worker. Per-connection
    TLS settings only take effect once a new TLS context is created, which is
    why ``OPT_X_TLS_NEWCTX`` must come last.

    See ``Config.LDAP_TLS_OPTION`` for what each value means. Note that
    ``OPT_X_TLS_NEVER`` is 0, so it must never be tested for truthiness.
    """
    tls_option = (current_app.config.get('LDAP_TLS_OPTION') or 'DEMAND').upper()
    if tls_option not in LDAP_TLS_OPTIONS:
        raise LdapConfigError(
            f"LDAP_TLS_OPTION must be one of {', '.join(LDAP_TLS_OPTIONS)}, got '{tls_option}'.")

    conn = ldap.initialize(current_app.config.get('LDAP_SERVER_URI'))
    conn.protocol_version = ldap.VERSION3
    conn.set_option(ldap.OPT_REFERRALS, 0)  # Often needed for AD/complex setups
    conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, getattr(ldap, f'OPT_X_TLS_{tls_option}'))
    ca_cert_file = current_app.config.get('LDAP_CA_CERT_FILE')
    if ca_cert_file:
        conn.set_option(ldap.OPT_X_TLS_CACERTFILE, ca_cert_file)
    conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    return conn


def _service_bind():
    """Connect and bind as the service account."""
    conn = _connect()
    conn.simple_bind_s(current_app.config.get('LDAP_BIND_USER'), current_app.config.get('LDAP_BIND_PASSWORD'))
    return conn


def _unbind_quietly(conn):
    if conn:
        try:
            conn.unbind_s()
        except ldap.LDAPError:
            pass


def _first(entry, attribute):
    """First value of an attribute as text, '' if absent. LDAP returns lists of bytes."""
    values = entry.get(attribute)
    return values[0].decode('utf-8') if values else ''


def _service_config_complete():
    return all(current_app.config.get(key) for key in
               ('LDAP_SERVER_URI', 'LDAP_USER_BASE_DN', 'LDAP_BIND_USER', 'LDAP_BIND_PASSWORD'))


def authenticate_user(username, password):
    """
    Authenticates a user against LDAP. If successful, searches for their uidNumber, gidNumber and mail.
    Returns a dictionary of user details {'uid':..., 'uidNumber':..., 'gidNumber':..., 'mail':...} on success, None otherwise.
    """
    if not current_app.config.get('LDAP_SERVER_URI') or not current_app.config.get('LDAP_USER_BASE_DN'):
        current_app.logger.error("LDAP_SERVER_URI or LDAP_USER_BASE_DN not configured.")
        return None
    if not username or not password:  # Don't attempt bind with empty credentials
        current_app.logger.warning("LDAP auth attempt with empty username or password.")
        return None

    # A service account is required to find the user's full DN and details.
    if not current_app.config.get('LDAP_BIND_USER') or not current_app.config.get('LDAP_BIND_PASSWORD'):
        current_app.logger.error("LDAP_BIND_USER and LDAP_BIND_PASSWORD must be configured for user search.")
        return None

    base_dn = current_app.config.get('LDAP_USER_BASE_DN')
    conn = None
    try:
        # 1. Bind with the service account to search for the user
        conn = _service_bind()

        search_filter = ldap.filter.filter_format('(uid=%s)', [username])
        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter,
                                ['uid', 'uidNumber', 'gidNumber', 'mail'])

        if len(results) != 1:
            current_app.logger.warning(
                f"LDAP search for '{username}' in base '{base_dn}' found {len(results)} entries. Authentication failed.")
            return None

        user_dn_found, entry = results[0]

        # 2. Verify the password by binding as the user, on a fresh connection.
        _unbind_quietly(conn)
        conn = _connect()
        conn.simple_bind_s(user_dn_found, password)
        current_app.logger.info(f"LDAP password verification successful for {user_dn_found}")

        # 3. Password is correct. Extract details from the entry found earlier.
        user_info = {
            'uid': _first(entry, 'uid'),
            'uidNumber': _first(entry, 'uidNumber'),
            'gidNumber': _first(entry, 'gidNumber'),
            'mail': _first(entry, 'mail') or None,
        }

        if not all([user_info['uid'], user_info['uidNumber'], user_info['gidNumber']]):
            current_app.logger.error(
                f"LDAP entry for {username} is missing uid, uidNumber, or gidNumber. Entry: {entry}")
            return None

        return user_info

    except LdapConfigError as e:
        current_app.logger.error(str(e))
        return None
    except ldap.INVALID_CREDENTIALS:
        current_app.logger.warning(f"LDAP invalid credentials for user '{username}' or service account.")
        return None
    except ldap.LDAPError as e:
        current_app.logger.error(f"LDAP Error during auth/search process for '{username}': {e}")
        return None
    finally:
        _unbind_quietly(conn)


def get_ldap_user_details(username):
    """
    Fetches details for a given LDAP user using the service bind account.
    This is used by the user_loader to refresh user info from the session ID.
    Returns a dictionary with uid, uidNumber, gidNumber, or None.
    """
    if not _service_config_complete():
        current_app.logger.error("LDAP configuration for service account search is incomplete.")
        return None

    conn = None
    try:
        conn = _service_bind()

        search_filter = ldap.filter.filter_format('(uid=%s)', [username])
        results = conn.search_s(current_app.config.get('LDAP_USER_BASE_DN'), ldap.SCOPE_SUBTREE,
                                search_filter, ['uid', 'uidNumber', 'gidNumber'])

        if len(results) == 1:
            _dn, entry = results[0]
            details = {
                'uid': _first(entry, 'uid'),
                'uidNumber': _first(entry, 'uidNumber'),
                'gidNumber': _first(entry, 'gidNumber'),
            }
            if all(details.values()):
                current_app.logger.debug(f"Found LDAP details for {username}: {details}")
                return details

        current_app.logger.warning(
            f"Could not find a unique and complete LDAP entry for {username} during detail fetch.")
        return None
    except LdapConfigError as e:
        current_app.logger.error(str(e))
        return None
    except ldap.LDAPError as e:
        current_app.logger.error(f"LDAP error getting details for {username}: {e}")
        return None
    finally:
        _unbind_quietly(conn)


def get_all_users_in_group():
    """
    Fetches all users from a configured LDAP group using the service bind account.
    This is used to populate the user search cache.
    Returns a list of dictionaries, e.g., [{'uid': 'j.doe', 'full_name': 'John Doe', 'mail': 'john.doe@rub.de'}], or None on failure.
    """
    # LDAP_USER_BASE_DN is the subtree of the single WhalePond access group
    # ("ccs-srv", modelled as an OU in RUB's directory). Every person under it
    # is a WhalePond user, so a subtree search here lists exactly the group's
    # members. (This is the LDAP access group -- NOT the WhalePond-internal
    # groups that govern resource/image permissions.)
    base_dn = current_app.config.get('LDAP_USER_BASE_DN')

    if not _service_config_complete():
        current_app.logger.error("LDAP configuration for group search is incomplete.")
        return None

    conn = None
    try:
        conn = _service_bind()

        # List every person under the base DN (= all WhalePond users). No
        # memberOf filter: ccs-srv is an OU, and its members are the person
        # entries in its subtree, not objects linking to it via memberOf. The
        # person class is site-specific (RUB uses rubPerson), hence configurable.
        object_class = current_app.config.get('LDAP_USER_OBJECT_CLASS') or 'rubPerson'
        search_filter = ldap.filter.filter_format('(objectClass=%s)', [object_class])
        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter, ['uid', 'cn', 'mail'])

        users_found = []
        for _dn, entry in results:
            uid = _first(entry, 'uid')
            if uid:  # Only add users that have a UID
                users_found.append({'uid': uid, 'full_name': _first(entry, 'cn'),
                                    'mail': _first(entry, 'mail') or None})

        current_app.logger.info(f"Found {len(users_found)} users under LDAP base DN '{base_dn}'.")
        return users_found

    except LdapConfigError as e:
        current_app.logger.error(str(e))
        return None
    except ldap.LDAPError as e:
        current_app.logger.error(f"LDAP error while fetching group members: {e}")
        return None
    finally:
        _unbind_quietly(conn)
