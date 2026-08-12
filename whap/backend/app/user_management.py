import logging
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


# --- User Loader ---
@login_manager.user_loader
def load_user(prefixed_user_id):
    """Loads the correct user wrapper object based on the ID prefix in the session."""
    logging.debug(f"load_user called with: {prefixed_user_id}")
    return load_user_by_identifier(prefixed_user_id)