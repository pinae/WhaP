import logging
import time

from flask import current_app, has_request_context, session
from flask_login import UserMixin
from . import db, login_manager
from .models import LocalUser, GroupMembership
from .services import ldap_service

def get_user_admin_status(user_id_str):
    """Checks if a user is in the admin group (ID 0)."""
    if not user_id_str:
        return False
    membership = db.session.scalar(db.select(GroupMembership).filter_by(user_uid=user_id_str, group_id=0))
    return membership is not None

# --- Abstract Base User Class for Flask-Login ---
# Inheriting from UserMixin provides default implementations for
# is_authenticated, is_active, is_anonymous, get_id
class User(UserMixin):
    def __init__(self, id_str):
        self.id_str = id_str # Stores prefixed ID ("local:1", "ldap:jdoe")

    def get_id(self):
        """Required by Flask-Login. Returns the unique ID stored in the session."""
        return self.id_str

    # --- Properties/Methods that subclasses must implement ---
    @property
    def user_type(self):
        raise NotImplementedError

    @property
    def username(self):
        raise NotImplementedError

    @property
    def is_admin(self):
        return get_user_admin_status(self.get_id())

    def get_project_owner_dict(self):
        raise NotImplementedError

    def get_container_user_dict(self):
        raise NotImplementedError

    def get_ansible_user_params(self):
        """Gets parameters needed for the Ansible playbook user setup."""
        raise NotImplementedError


# --- Concrete Wrapper for Local DB Users ---
class LocalUserWrapper(User):
    def __init__(self, local_user_db):
        self.db_user = local_user_db
        super().__init__(f"local:{self.db_user.id}")

    @property
    def user_type(self):
        return 'local'

    @property
    def username(self):
        return self.db_user.username

    @property
    def email(self):
        return self.db_user.email

    def get_project_owner_dict(self):
        return {'owner_local_user_id': self.db_user.id, 'owner_uid': None}

    def get_container_user_dict(self):
        return {'user_local_user_id': self.db_user.id, 'user_uid': None}

    def get_ansible_user_params(self):
        """For local users, provide default values as requested."""
        return {
            'user': self.username,
            'user_id': '1000',
            'group_id': '1000'
        }


# --- Concrete Wrapper for LDAP Users ---
class LdapUserWrapper(User):
    def __init__(self, ldap_user_details):
        """Takes a dictionary of details from ldap_service."""
        self.details = ldap_user_details
        super().__init__(f"ldap:{self.details['uid']}")

    @property
    def user_type(self):
        return 'ldap'

    @property
    def username(self):
        return self.details['uid']

    @property
    def uid_number(self):
        return self.details.get('uidNumber')

    @property
    def gid_number(self):
        return self.details.get('gidNumber')

    @property
    def email(self):
        """The directory's mail attribute, as of sign-in or the last check; None if unknown."""
        return self.details.get('mail')

    def get_project_owner_dict(self):
        return {'owner_local_user_id': None, 'owner_uid': self.username}

    def get_container_user_dict(self):
        return {'user_local_user_id': None, 'user_uid': self.username}

    def get_ansible_user_params(self):
        """For LDAP users, provide the IDs fetched from LDAP."""
        return {
            'user': self.username,
            'user_id': self.uid_number,
            'group_id': self.gid_number
        }

def load_user_by_identifier(prefixed_user_id):
    """
    Loads the correct user wrapper object based on a prefixed ID string.
    Can be called from background jobs or services.
    """
    if not prefixed_user_id:
        return None
    try:
        prefix, actual_id = prefixed_user_id.split(":", 1)
    except (ValueError, AttributeError):
        logging.error(f"Invalid user ID format: {prefixed_user_id}")
        return None

    if prefix == 'local':
        try:
            local_user_db = db.session.get(LocalUser, int(actual_id))
            if local_user_db:
                return LocalUserWrapper(local_user_db)
            logging.warning(f"Local user ID {actual_id} not found in DB.")
            return None
        except ValueError:
            logging.error(f"Invalid local user ID (non-integer): {actual_id}")
            return None

    elif prefix == 'ldap':
        ldap_details = ldap_service.get_ldap_user_details(actual_id)
        if ldap_details:
            return LdapUserWrapper(ldap_details)
        logging.warning(f"Could not load details for LDAP user '{actual_id}'.")
        return None

    logging.error(f"Unknown user prefix in identifier: {prefix}")
    return None


# --- LDAP users' details in their session ---
# Flask-Login loads the user on every request. Asking LDAP each time (a new
# TLS connection, bind and search) made every page wait for LDAP about ten
# times, and signed everyone out whenever LDAP was down. The details are
# kept in the (signed) session from sign-in on, and LDAP is asked again
# once every LDAP_RECHECK_HOURS.

LDAP_SESSION_KEY = 'ldap_user'
_now = time.time  # tests move the clock


def remember_ldap_user(details):
    """Keep a signed-in LDAP user's details in their session until the next check."""
    session[LDAP_SESSION_KEY] = {
        'uid': details['uid'], 'uidNumber': details.get('uidNumber'), 'gidNumber': details.get('gidNumber'),
        'mail': details.get('mail'),
        'check_at': _now() + current_app.config.get('LDAP_RECHECK_HOURS', 24) * 3600,
    }


def forget_ldap_user():
    session.pop(LDAP_SESSION_KEY, None)


def _load_ldap_session_user(uid):
    """The user from their session; from LDAP once the session's details are due for a check.

    An account LDAP no longer has is signed out. If LDAP can't be reached the
    user stays signed in with what the session knows, and the check waits
    LDAP_RETRY_MINUTES instead of going to LDAP on every request.
    """
    stored = session.get(LDAP_SESSION_KEY)
    if not stored or stored.get('uid') != uid:
        stored = None  # signed in before details were kept in the session
    elif _now() < stored.get('check_at', 0):
        return LdapUserWrapper(stored)

    try:
        details = ldap_service.find_ldap_user(uid)
    except ldap_service.LdapUnavailable as e:
        logging.warning(f"Could not recheck LDAP user '{uid}', keeping them signed in: {e}")
        stored = stored or {'uid': uid, 'uidNumber': None, 'gidNumber': None, 'mail': None}
        session[LDAP_SESSION_KEY] = {
            **stored, 'check_at': _now() + current_app.config.get('LDAP_RETRY_MINUTES', 5) * 60}
        return LdapUserWrapper(stored)

    if not details:
        logging.warning(f"LDAP no longer has user '{uid}'; signing them out.")
        forget_ldap_user()
        # Flask-Login keeps the id in the session when the loader finds no
        # user; without this, each later request would ask LDAP again.
        session.pop('_user_id', None)
        session.pop('_fresh', None)
        return None
    remember_ldap_user(details)
    return LdapUserWrapper(details)


# --- User Loader ---
@login_manager.user_loader
def load_user(prefixed_user_id):
    """Loads the correct user wrapper object based on the ID prefix in the session."""
    logging.debug(f"load_user called with: {prefixed_user_id}")
    if has_request_context() and isinstance(prefixed_user_id, str) and prefixed_user_id.startswith('ldap:'):
        return _load_ldap_session_user(prefixed_user_id.split(':', 1)[1])
    return load_user_by_identifier(prefixed_user_id)