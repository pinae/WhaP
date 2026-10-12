"""Who a notification is for, and how each of them can be reached."""
from collections import defaultdict
from dataclasses import dataclass, field

from .. import db
from ..models import ContainerInstance, ContainerMount, GroupMembership, LocalUser, NotificationSettings
from ..services.ldap_service import LdapUnavailable, get_all_users_in_group, get_ldap_contacts


@dataclass
class Recipient:
    user_uid: str  # "local:<id>" or "ldap:<uid>"
    username: str
    name: str  # to greet them by
    email: str | None
    settings: NotificationSettings
    kind: str
    containers: list = field(default_factory=list)  # the ones this notification is about

    def channels(self):
        """[(channel, address)] this person gets the notification on; empty if none."""
        if not self.settings.wants(self.kind):
            return []
        found = []
        for channel in self.settings.channels():
            if channel == 'email' and self.email:
                found.append(('email', self.email))
            elif channel == 'matrix':
                found.append(('matrix', self.settings.matrix_id))
        return found

    @property
    def unreachable(self):
        """Why this person won't get it, or None:
        'topic_off', 'all_off' (no channel switched on) or 'no_address'."""
        if self.channels():
            return None
        if not self.settings.wants(self.kind):
            return 'topic_off'
        if not self.settings.channels():
            return 'all_off'
        return 'no_address'


def _containers(notification):
    params = notification.params_dict
    query = db.select(ContainerInstance).where(ContainerInstance.status != 'DELETED')
    if notification.kind == 'maintenance':
        query = query.where(ContainerInstance.compute_server_id.in_(params.get('server_ids') or []))
    elif notification.kind == 'image':
        query = query.where(ContainerInstance.image_name == params.get('image'))
    elif notification.kind == 'dataset':
        query = query.where(ContainerInstance.mounts.any(ContainerMount.dataset == params.get('dataset')))
    elif notification.kind == 'expiry':
        query = query.where(ContainerInstance.id == params.get('container_id'))
    elif notification.kind in ('announcement', 'group'):
        # Recipients are chosen otherwise (_everyone, _members); their
        # containers are listed but don't make them recipients.
        pass
    return db.session.scalars(query.order_by(ContainerInstance.id)).all()


def _everyone():
    """Every WhaP user: the LDAP access group and all local users."""
    members = get_all_users_in_group()
    if members is None:
        raise LdapUnavailable("Could not list the users in LDAP.")
    uids = {f"ldap:{m['uid']}" for m in members}
    uids |= {f"local:{user_id}" for user_id in db.session.scalars(db.select(LocalUser.id))}
    return uids


def _members(group_ids):
    """The members of these WhaP groups."""
    return set(db.session.scalars(
        db.select(GroupMembership.user_uid).where(GroupMembership.group_id.in_(group_ids or []))))


def recipients(notification):
    """Everyone ``notification`` concerns, reachable or not, by username.

    Raises LdapUnavailable when the directory can't be asked: sending to
    nobody because LDAP was down would look like success.
    """
    by_user = defaultdict(list)
    for container in _containers(notification):
        by_user[container.owner_identifier].append(container)
    if notification.kind == 'announcement':
        uids = _everyone() | set(by_user)
    elif notification.kind == 'group':
        uids = _members(notification.params_dict.get('group_ids'))
    else:
        uids = set(by_user)

    ldap_uids = [uid.split(':', 1)[1] for uid in uids if uid.startswith('ldap:')]
    contacts = get_ldap_contacts(ldap_uids)
    local_ids = [int(uid.split(':', 1)[1]) for uid in uids if uid.startswith('local:')]
    local_users = {u.id: u for u in db.session.scalars(db.select(LocalUser).where(LocalUser.id.in_(local_ids)))}
    saved = {s.user_uid: s for s in db.session.scalars(
        db.select(NotificationSettings).where(NotificationSettings.user_uid.in_(uids)))}

    found = []
    for uid in uids:
        prefix, ident = uid.split(':', 1)
        if prefix == 'local':
            user = local_users.get(int(ident))
            if not user:
                continue  # a deleted local user's leftover container
            username, name, email = user.username, user.username, user.email
        else:
            contact = contacts.get(ident, {})
            username, name, email = ident, contact.get('name') or ident, contact.get('mail')
        found.append(Recipient(user_uid=uid, username=username, name=name, email=email,
                               settings=saved.get(uid) or NotificationSettings(user_uid=uid),
                               kind=notification.kind, containers=by_user.get(uid, [])))
    return sorted(found, key=lambda r: r.username)
