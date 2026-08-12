import ldap
import ldap.filter
from flask import current_app


def authenticate_user(username, password):
    """
    Authenticates a user against LDAP. If successful, searches for their uidNumber, gidNumber and mail.
    Returns a dictionary of user details {'uid':..., 'uidNumber':..., 'gidNumber':..., 'mail':...} on success, None otherwise.
    """
    uri = current_app.config.get('LDAP_SERVER_URI')
    base_dn = current_app.config.get('LDAP_USER_BASE_DN')
    bind_user_dn = current_app.config.get('LDAP_BIND_USER')
    bind_user_password = current_app.config.get('LDAP_BIND_PASSWORD')

    if not uri or not base_dn:
        current_app.logger.error("LDAP_SERVER_URI or LDAP_USER_BASE_DN not configured.")
        return None
    if not username or not password:  # Don't attempt bind with empty credentials
        current_app.logger.warning("LDAP auth attempt with empty username or password.")
        return None

    # A service account is required to find the user's full DN and details.
    if not bind_user_dn or not bind_user_password:
        current_app.logger.error("LDAP_BIND_USER and LDAP_BIND_PASSWORD must be configured for user search.")
        return None

    conn = None
    try:
        # Use LDAPS, require cert if possible for security
        # Adjust TLS options based on server setup (ALLOW, DEMAND, NEVER)
        tls_option = current_app.config.get('LDAP_TLS_OPTION', 'DEMAND').upper()
        if tls_option == 'DEMAND':
            ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
        elif tls_option == 'ALLOW':
            ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_ALLOW)

        # Ensure cert file path is set if using DEMAND/ALLOW with self-signed certs etc.
        # ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, current_app.config.get('LDAP_CA_CERT_FILE'))

        conn = ldap.initialize(uri)
        conn.protocol_version = ldap.VERSION3
        conn.set_option(ldap.OPT_REFERRALS, 0)  # Often needed for AD/complex setups

        # 1. Bind with the service account to search for the user
        conn.simple_bind_s(bind_user_dn, bind_user_password)
        current_app.logger.debug(f"LDAP search: Bound with service account '{bind_user_dn}'.")

        search_filter = ldap.filter.filter_format('(uid=%s)', [username])
        attributes_to_fetch = ['dn', 'uid', 'uidNumber', 'gidNumber', 'mail']

        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter, attributes_to_fetch)

        if len(results) != 1:
            current_app.logger.warning(
                f"LDAP search for '{username}' in base '{base_dn}' found {len(results)} entries. Authentication failed.")
            return None

        user_dn_found, entry = results[0]

        # 2. Unbind service account and re-bind as the user to verify their password
        # A new connection object is cleaner than unbinding and rebinding the same one.
        conn.unbind_s()
        conn = ldap.initialize(uri)
        conn.protocol_version = ldap.VERSION3
        conn.set_option(ldap.OPT_REFERRALS, 0)

        conn.simple_bind_s(user_dn_found, password)
        current_app.logger.info(f"LDAP password verification successful for {user_dn_found}")

        # 3. If we are here, password is correct. Extract details from the entry we found earlier.
        # LDAP attributes are returned as lists of byte strings.
        user_info = {
            'uid': entry.get('uid', [b''])[0].decode('utf-8'),
            'uidNumber': entry.get('uidNumber', [b''])[0].decode('utf-8'),
            'gidNumber': entry.get('gidNumber', [b''])[0].decode('utf-8'),
            'mail': entry.get('mail', [b''])[0].decode('utf-8') if entry.get('mail') else None
        }

        if not all([user_info['uid'], user_info['uidNumber'], user_info['gidNumber']]):
            current_app.logger.error(
                f"LDAP entry for {username} is missing uid, uidNumber, or gidNumber. Entry: {entry}")
            return None

        return user_info

    except ldap.INVALID_CREDENTIALS:
        current_app.logger.warning(f"LDAP invalid credentials for user '{username}' or service account.")
        return None
    except ldap.LDAPError as e:
        current_app.logger.error(f"LDAP Error during auth/search process for '{username}': {e}")
        return None
    finally:
        if conn:
            try:
                conn.unbind_s()
            except ldap.LDAPError:
                pass


def get_ldap_user_details(username):
    """
    Fetches details for a given LDAP user using the service bind account.
    This is used by the user_loader to refresh user info from the session ID.
    Returns a dictionary with uid, uidNumber, gidNumber, or None.
    """
    uri = current_app.config.get('LDAP_SERVER_URI')
    base_dn = current_app.config.get('LDAP_USER_BASE_DN')
    bind_user_dn = current_app.config.get('LDAP_BIND_USER')
    bind_user_password = current_app.config.get('LDAP_BIND_PASSWORD')

    if not all([uri, base_dn, bind_user_dn, bind_user_password]):
        current_app.logger.error("LDAP configuration for service account search is incomplete.")
        return None

    conn = None
    try:
        # Initialize and set TLS options
        tls_option = current_app.config.get('LDAP_TLS_OPTION', 'DEMAND').upper()
        if tls_option == 'DEMAND':
            ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
        elif tls_option == 'ALLOW':
            ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_ALLOW)

        conn = ldap.initialize(uri)
        conn.protocol_version = ldap.VERSION3
        conn.set_option(ldap.OPT_REFERRALS, 0)

        conn.simple_bind_s(bind_user_dn, bind_user_password)

        search_filter = ldap.filter.filter_format('(uid=%s)', [username])
        attributes = ['uid', 'uidNumber', 'gidNumber']
        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter, attributes)

        if len(results) == 1:
            _dn, entry = results[0]
            details = {
                'uid': entry.get('uid', [b''])[0].decode('utf-8'),
                'uidNumber': entry.get('uidNumber', [b''])[0].decode('utf-8'),
                'gidNumber': entry.get('gidNumber', [b''])[0].decode('utf-8')
            }
            if all(details.values()):
                current_app.logger.debug(f"Found LDAP details for {username}: {details}")
                return details

        current_app.logger.warning(
            f"Could not find a unique and complete LDAP entry for {username} during detail fetch.")
        return None
    except ldap.LDAPError as e:
        current_app.logger.error(f"LDAP error getting details for {username}: {e}")
        return None
    finally:
        if conn:
            try:
                conn.unbind_s()
            except ldap.LDAPError:
                pass


def get_all_users_in_group():
    """
    Fetches all users from a configured LDAP group using the service bind account.
    This is used to populate the user search cache.
    Returns a list of dictionaries, e.g., [{'uid': 'j.doe', 'full_name': 'John Doe', 'mail': 'john.doe@rub.de'}], or None on failure.
    """
    uri = current_app.config.get('LDAP_SERVER_URI')
    # LDAP_USER_BASE_DN is the subtree of the single WhalePond access group
    # ("ccs-srv", modelled as an OU in RUB's directory). Every rubPerson under it
    # is a WhalePond user, so a subtree search here lists exactly the group's
    # members. (This is the LDAP access group -- NOT the WhalePond-internal
    # groups that govern resource/image permissions.)
    base_dn = current_app.config.get('LDAP_USER_BASE_DN')
    bind_user_dn = current_app.config.get('LDAP_BIND_USER')
    bind_user_password = current_app.config.get('LDAP_BIND_PASSWORD')

    if not all([uri, base_dn, bind_user_dn, bind_user_password]):
        current_app.logger.error("LDAP configuration for group search is incomplete.")
        return None

    conn = None
    try:
        # Initialize and set TLS options
        tls_option = current_app.config.get('LDAP_TLS_OPTION', 'DEMAND').upper()
        if tls_option == 'DEMAND':
            ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
        elif tls_option == 'ALLOW':
            ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_ALLOW)

        conn = ldap.initialize(uri)
        conn.protocol_version = ldap.VERSION3
        conn.set_option(ldap.OPT_REFERRALS, 0)

        # Bind with the service account to perform the search
        conn.simple_bind_s(bind_user_dn, bind_user_password)

        # List every person under the ccs-srv base DN (= all WhalePond users).
        # No memberOf filter: ccs-srv is an OU, and its members are the person
        # entries in its subtree, not objects linking to it via memberOf.
        search_filter = ldap.filter.filter_format("(objectClass=rubPerson)", [])
        attributes_to_fetch = ['uid', 'cn', 'mail']

        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter, attributes_to_fetch)

        users_found = []
        for _dn, entry in results:
            uid = entry.get('uid', [b''])[0].decode('utf-8')
            full_name = entry.get('cn', [b''])[0].decode('utf-8')
            mail = entry.get('mail', [b''])[0].decode('utf-8') if entry.get('mail') else None
            if uid:  # Only add users that have a UID
                users_found.append({'uid': uid, 'full_name': full_name, 'mail': mail})

        current_app.logger.info(f"Found {len(users_found)} users under LDAP base DN '{base_dn}'.")
        return users_found

    except ldap.LDAPError as e:
        current_app.logger.error(f"LDAP error while fetching group members: {e}")
        return None
    finally:
        if conn:
            try:
                conn.unbind_s()
            except ldap.LDAPError:
                pass
