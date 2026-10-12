"""Fakes for notification tests, loaded by conftest as a plugin.

Email goes to a real SMTP server (aiosmtpd) on localhost (``mail``). The Matrix
homeserver is a fake that records requests and answers as told
(``homeserver``). LDAP is a dictionary (``directory``).
"""
import email
import socket
from email import policy

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult

from app.notifications import audience
from app.services import notification_service
from app.services.ldap_service import LdapUnavailable

CONTACTS = {
    "alice": {"mail": "alice@uni.example", "name": "Alice"},
    "bob": {"mail": None, "name": "Bob"},
    "dave": {"mail": "dave@uni.example", "name": "Dave"},
    "erin": {"mail": "erin@uni.example", "name": "Erin"},
    "frank": {"mail": "frank@uni.example", "name": "Frank"},
    "unknown": {"mail": "unknown@uni.example", "name": "Unknown"},
    "busy": {"mail": "busy@uni.example", "name": "Busy"},
}


class MailServer:
    """Accepts mail like a real server; 'unknown@' is refused for good, 'busy@' for now."""

    def __init__(self):
        self.messages = []
        self.logins = []

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if address.startswith("unknown@"):
            return "550 5.1.1 mailbox unavailable"
        if address.startswith("busy@"):
            return "451 4.3.0 try again later"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(email.message_from_bytes(envelope.content, policy=policy.default))
        return "250 OK"

    def authenticate(self, server, session, envelope, mechanism, auth_data):
        self.logins.append((auth_data.login.decode(), auth_data.password.decode()))
        return AuthResult(success=auth_data.password == b"right")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mail(app):
    server = MailServer()
    port = free_port()
    controller = Controller(server, hostname="127.0.0.1", port=port,
                            authenticator=server.authenticate, auth_require_tls=False)
    controller.start()
    app.config.update(SMTP_SERVER="127.0.0.1", SMTP_PORT=str(port), SMTP_SECURITY="none",
                      SMTP_USERNAME=None, SMTP_PASSWORD=None, SENDER_EMAIL="whap@uni.example",
                      SENDER_NAME="WhaP", WHAP_URL="https://whap.uni.example", TIMEZONE="Europe/Berlin")
    yield server
    controller.stop()


class Reply:
    def __init__(self, status, data=None):
        self.status_code = status
        self.ok = status < 400
        self.data = data

    def json(self):
        if self.data is None:
            raise ValueError("no JSON")
        return self.data


class Homeserver:
    """Records requests; answers with queued replies, else success."""

    def __init__(self):
        self.calls = []
        self.replies = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        reply = self.replies.pop(0) if self.replies else Reply(200, {"event_id": "$event", "room_id": "!new:x"})
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def homeserver(app, monkeypatch):
    server = Homeserver()
    monkeypatch.setattr("app.notifications.matrix_channel.requests.Session", lambda: server)
    app.config.update(MATRIX_HOMESERVER_URL="https://matrix.uni.example", MATRIX_ACCESS_TOKEN="syt_secret")
    return server


@pytest.fixture
def directory(monkeypatch):
    """LDAP as a dictionary: CONTACTS, and everyone() listing them all."""
    state = {"down": False}

    def contacts(uids):
        if state["down"]:
            raise LdapUnavailable("directory down")
        return {uid: CONTACTS[uid] for uid in uids if uid in CONTACTS}

    def everyone():
        return None if state["down"] else [{"uid": uid} for uid in ("alice", "bob")]

    monkeypatch.setattr(audience, "get_ldap_contacts", contacts)
    monkeypatch.setattr(audience, "get_all_users_in_group", everyone)
    monkeypatch.setattr(notification_service, "get_ldap_contacts", contacts)
    return state
