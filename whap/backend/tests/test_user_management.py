"""Tests for app.user_management.

This module is the auth foundation: the Flask-Login user loader, the
local/LDAP user wrappers, and the admin-status check. A lot of routing and
permission code depends on the wrapper contract (get_id / user_type /
get_project_owner_dict / get_container_user_dict / get_ansible_user_params), so
it's worth pinning precisely.
"""
import pytest

from app.user_management import (
    get_user_admin_status,
    LocalUserWrapper,
    LdapUserWrapper,
    load_user_by_identifier,
    load_user,
)
from app.models import GroupMembership


# --- get_user_admin_status --------------------------------------------------

def test_admin_status_false_for_empty_id(app):
    assert get_user_admin_status(None) is False
    assert get_user_admin_status("") is False


def test_admin_status_true_for_group0_member(app, db, make_local_user):
    user = make_local_user(username="adminy")
    db.session.add(GroupMembership(user_uid=f"local:{user.id}", group_id=0))
    db.session.commit()
    assert get_user_admin_status(f"local:{user.id}") is True


def test_admin_status_false_for_non_member(app, db, make_local_user):
    user = make_local_user(username="plain")
    assert get_user_admin_status(f"local:{user.id}") is False


# --- LocalUserWrapper -------------------------------------------------------

def test_local_wrapper_contract(app, db, make_local_user):
    user = make_local_user(username="alice")
    w = LocalUserWrapper(user)

    assert w.get_id() == f"local:{user.id}"
    assert w.user_type == "local"
    assert w.username == "alice"
    assert w.get_project_owner_dict() == {'owner_local_user_id': user.id, 'owner_uid': None}
    assert w.get_container_user_dict() == {'user_local_user_id': user.id, 'user_uid': None}
    assert w.get_ansible_user_params() == {'user': 'alice', 'user_id': '1000', 'group_id': '1000'}


def test_local_wrapper_is_admin_reflects_membership(app, db, make_local_user):
    user = make_local_user(username="localadmin")
    w = LocalUserWrapper(user)
    assert w.is_admin is False
    db.session.add(GroupMembership(user_uid=f"local:{user.id}", group_id=0))
    db.session.commit()
    assert w.is_admin is True


# --- LdapUserWrapper (no DB; pure details dict) -----------------------------

def _ldap_details(**over):
    base = {'uid': 'jdoe', 'uidNumber': '5001', 'gidNumber': '6001'}
    base.update(over)
    return base


def test_ldap_wrapper_contract(app):
    w = LdapUserWrapper(_ldap_details())
    assert w.get_id() == "ldap:jdoe"
    assert w.user_type == "ldap"
    assert w.username == "jdoe"
    assert w.uid_number == "5001"
    assert w.gid_number == "6001"
    assert w.get_project_owner_dict() == {'owner_local_user_id': None, 'owner_uid': 'jdoe'}
    assert w.get_container_user_dict() == {'user_local_user_id': None, 'user_uid': 'jdoe'}
    assert w.get_ansible_user_params() == {'user': 'jdoe', 'user_id': '5001', 'group_id': '6001'}


def test_ldap_wrapper_missing_id_numbers_are_none(app):
    w = LdapUserWrapper({'uid': 'nonums'})
    assert w.uid_number is None
    assert w.gid_number is None
    assert w.get_ansible_user_params() == {'user': 'nonums', 'user_id': None, 'group_id': None}


# --- load_user_by_identifier ------------------------------------------------

def test_load_none_or_empty_returns_none(app):
    assert load_user_by_identifier(None) is None
    assert load_user_by_identifier("") is None


def test_load_malformed_identifier_returns_none(app):
    # No ':' separator -> ValueError caught -> None.
    assert load_user_by_identifier("garbage") is None


def test_load_unknown_prefix_returns_none(app):
    assert load_user_by_identifier("saml:foo") is None


def test_load_local_user_found(app, db, make_local_user):
    user = make_local_user(username="loadme")
    w = load_user_by_identifier(f"local:{user.id}")
    assert isinstance(w, LocalUserWrapper)
    assert w.get_id() == f"local:{user.id}"


def test_load_local_user_not_found_returns_none(app, db):
    assert load_user_by_identifier("local:999999") is None


def test_load_local_non_integer_id_returns_none(app, db):
    # int("abc") raises ValueError inside the local branch -> None.
    assert load_user_by_identifier("local:abc") is None


def test_load_ldap_user_found(app, monkeypatch):
    import app.user_management as um
    monkeypatch.setattr(
        um.ldap_service, "get_ldap_user_details",
        lambda uid: {'uid': uid, 'uidNumber': '7000', 'gidNumber': '7000'}
    )
    w = load_user_by_identifier("ldap:bob")
    assert isinstance(w, LdapUserWrapper)
    assert w.username == "bob"
    assert w.uid_number == "7000"


def test_load_ldap_user_not_found_returns_none(app, monkeypatch):
    import app.user_management as um
    monkeypatch.setattr(um.ldap_service, "get_ldap_user_details", lambda uid: None)
    assert load_user_by_identifier("ldap:ghost") is None


# --- load_user (the Flask-Login loader delegates to the above) --------------

def test_user_loader_delegates(app, db, make_local_user):
    user = make_local_user(username="loader")
    w = load_user(f"local:{user.id}")
    assert isinstance(w, LocalUserWrapper)
    assert w.get_id() == f"local:{user.id}"


def test_base_user_notimplemented_contract():
    """The abstract base raises NotImplementedError for the subclass hooks."""
    from app.user_management import User
    u = User("local:1")
    for call in (
            lambda: u.user_type,
            lambda: u.username,
            u.get_project_owner_dict,
            u.get_container_user_dict,
            u.get_ansible_user_params,
    ):
        with pytest.raises(NotImplementedError):
            call()
