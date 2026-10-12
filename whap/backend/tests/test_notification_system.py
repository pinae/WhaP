"""Where a user's notifications go: get_user_email.

Local users' addresses: test_notification_models.py. Sending: test_notification_delivery.py.
"""
from app.services import notification_service
from app.services.ldap_service import LdapUnavailable
from app.services.notification_service import get_user_email


def test_an_ldap_users_address_comes_from_the_directory(app, monkeypatch):
    asked = []

    def contacts(uids):
        asked.append(list(uids))
        return {"jdoe": {"mail": "john.doe@example.com", "name": "John"}}

    monkeypatch.setattr(notification_service, "get_ldap_contacts", contacts)
    assert get_user_email("ldap:jdoe") == "john.doe@example.com"
    assert asked == [["jdoe"]]


def test_an_ldap_user_without_mail_has_no_address(app, monkeypatch):
    monkeypatch.setattr(notification_service, "get_ldap_contacts",
                        lambda uids: {"jdoe": {"mail": None, "name": "John"}})
    assert get_user_email("ldap:jdoe") is None


def test_an_unknown_ldap_user_has_no_address(app, monkeypatch):
    monkeypatch.setattr(notification_service, "get_ldap_contacts", lambda uids: {})
    assert get_user_email("ldap:ghost") is None


def test_a_directory_outage_gives_no_address_instead_of_an_error(app, monkeypatch):
    def down(uids):
        raise LdapUnavailable("down")

    monkeypatch.setattr(notification_service, "get_ldap_contacts", down)
    assert get_user_email("ldap:jdoe") is None


def test_malformed_identifiers_have_no_address(app):
    assert get_user_email("invalid-format") is None
    assert get_user_email("group:1") is None
    assert get_user_email(None) is None
