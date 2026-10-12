"""Looking up where a user's notifications go. Sending is in app.notifications."""
import logging
from .. import db
from ..models import LocalUser
from .ldap_service import get_ldap_contacts, LdapUnavailable

def get_user_email(user_id_str):
    """The email address notifications for a user go to, or None.

    ``user_id_str`` is "local:<id>" or "ldap:<uid>". LDAP users' addresses come
    from the directory's mail attribute, local users' from their record.
    """
    if not user_id_str:
        return None

    try:
        prefix, actual_id = user_id_str.split(":", 1)
    except (ValueError, AttributeError):
        logging.error(f"Invalid user ID format: {user_id_str}")
        return None

    if prefix == 'local':
        try:
            user = db.session.get(LocalUser, int(actual_id))
        except ValueError:
            return None
        return user.email if user else None

    elif prefix == 'ldap':
        try:
            return get_ldap_contacts([actual_id]).get(actual_id, {}).get('mail')
        except LdapUnavailable as e:
            logging.warning(str(e))
            return None

    logging.error(f"Unknown user prefix in identifier: {prefix}")
    return None
