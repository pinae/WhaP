"""A signed-in LDAP user costs LDAP one lookup a day, not one per request.

Flask-Login loads the user on every request. It used to ask LDAP each time (a
new TLS connection, bind and search): opening the User Panel made about ten
such lookups, the settings page one more for the address, the server stats
one per server every minute. And while LDAP was down every LDAP user was
signed out.

Now the details LDAP returns at sign-in stay in the session, and LDAP is asked
again once every LDAP_RECHECK_HOURS: an account removed there is signed out
then. If LDAP can't be reached for that check the user stays signed in, and
the check waits LDAP_RETRY_MINUTES instead of being tried on every request.

The test client loads the user anew for each request, as production does
(conftest's _FreshUserClient); otherwise one lookup per test would hide a
lookup per request.
"""
import pytest

import app.user_management as user_management
from app.services import ldap_service

# What the User Panel asks for when it opens.
USER_PANEL = ["/auth/session", "/api/notices", "/api/servers", "/api/containers", "/api/sshkeys", "/api/projects",
              "/api/groups", "/api/permissions/my-permissions", "/api/notification-settings",
              "/api/permissions/my-available-images"]
HOUR = 3600


class Ldap:
    """LDAP as a dictionary, counting every time it is asked."""

    def __init__(self):
        self.users = {"alice": {"uid": "alice", "uidNumber": "70001", "gidNumber": "70000",
                                "mail": "alice@uni.example"}}
        self.down = False
        self.asked = []

    def _ask(self, what):
        self.asked.append(what)
        if self.down:
            raise ldap_service.LdapUnavailable("LDAP is down")

    def authenticate_user(self, username, password):
        try:
            self._ask(("sign-in", username))
        except ldap_service.LdapUnavailable:
            return None
        return self.users.get(username) if password == "pw" else None

    def find_ldap_user(self, username):
        self._ask(("lookup", username))
        return self.users.get(username)

    def get_ldap_user_details(self, username):
        try:
            return self.find_ldap_user(username)
        except ldap_service.LdapUnavailable:
            return None

    def get_ldap_contacts(self, uids):
        self._ask(("contacts", tuple(uids)))
        return {uid: {"mail": self.users[uid]["mail"], "name": uid} for uid in uids if uid in self.users}


@pytest.fixture
def ldap(monkeypatch):
    fake = Ldap()
    for name in ("authenticate_user", "find_ldap_user", "get_ldap_user_details", "get_ldap_contacts"):
        monkeypatch.setattr(ldap_service, name, getattr(fake, name))
    monkeypatch.setattr("app.services.notification_service.get_ldap_contacts", fake.get_ldap_contacts)
    return fake


@pytest.fixture
def clock(monkeypatch):
    """The time the session's next LDAP check is measured against; clock.advance(hours=...)."""
    class Clock:
        now = 1_800_000_000.0

        def advance(self, hours=0, minutes=0):
            self.now += hours * HOUR + minutes * 60

    c = Clock()
    monkeypatch.setattr(user_management, "_now", lambda: c.now)
    return c


@pytest.fixture
def alice(client, db, ldap, clock):
    """alice, signed in through LDAP; the lookups so far are forgotten."""
    response = client.post("/auth/login", json={"username": "alice", "password": "pw"})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert ldap.asked == [("sign-in", "alice")], "signing in asks LDAP once"
    ldap.asked.clear()
    return client


def open_user_panel(client):
    for url in USER_PANEL:
        response = client.get(url)
        assert response.status_code == 200, f"{url}: {response.status_code}"


def test_using_whap_all_day_does_not_ask_ldap(alice, ldap, clock):
    for _ in range(24):
        open_user_panel(alice)
        clock.advance(hours=0.99)
    assert ldap.asked == [], f"{len(ldap.asked)} LDAP requests for {24 * len(USER_PANEL)} page requests"


def test_the_address_comes_from_the_sign_in(alice, ldap):
    settings = alice.get("/api/notification-settings").get_json()
    assert settings["email"]["address"] == "alice@uni.example"
    assert ldap.asked == []


def test_the_account_is_checked_once_a_day(alice, ldap, clock):
    clock.advance(hours=23.9)
    open_user_panel(alice)
    assert ldap.asked == []

    clock.advance(hours=0.2)
    ldap.users["alice"]["mail"] = "alice@new.example"
    for _ in range(3):
        open_user_panel(alice)
    assert ldap.asked == [("lookup", "alice")], "one check, then a day's rest"
    assert alice.get("/api/notification-settings").get_json()["email"]["address"] == "alice@new.example"


def test_an_account_removed_from_ldap_is_signed_out_at_the_check(alice, ldap, clock):
    del ldap.users["alice"]
    open_user_panel(alice)  # within the day: still signed in
    clock.advance(hours=25)
    assert alice.get("/api/containers").status_code == 401
    assert alice.get("/auth/session").get_json()["isLoggedIn"] is False
    assert ldap.asked == [("lookup", "alice")]


def test_users_stay_signed_in_while_ldap_is_down_and_ldap_is_not_flooded(alice, ldap, clock):
    clock.advance(hours=25)
    ldap.down = True
    for _ in range(5):
        open_user_panel(alice)
    assert ldap.asked == [("lookup", "alice")], "one failed check, not one per request"
    assert alice.get("/auth/session").get_json()["user"]["username"] == "alice"

    clock.advance(minutes=4)
    open_user_panel(alice)
    assert len(ldap.asked) == 1, "the next try waits LDAP_RETRY_MINUTES"

    clock.advance(minutes=2)
    open_user_panel(alice)
    assert len(ldap.asked) == 2, "tried again, still down"

    ldap.down = False
    clock.advance(minutes=6)
    for _ in range(3):
        open_user_panel(alice)
    assert len(ldap.asked) == 3, "LDAP is back: checked, and good for another day"
    clock.advance(hours=23)
    open_user_panel(alice)
    assert len(ldap.asked) == 3


def test_a_session_from_before_details_were_kept_is_checked_once(client, db, ldap, clock):
    with client.session_transaction() as session:  # what a sign-in used to leave
        session["_user_id"] = "ldap:alice"
        session["_fresh"] = True
    for _ in range(3):
        open_user_panel(client)
    assert ldap.asked == [("lookup", "alice")]
    assert client.get("/api/notification-settings").get_json()["email"]["address"] == "alice@uni.example"


def test_details_kept_for_another_user_are_not_used(client, db, ldap, clock):
    with client.session_transaction() as session:
        session["_user_id"] = "ldap:alice"
        session[user_management.LDAP_SESSION_KEY] = {"uid": "bob", "uidNumber": "1", "gidNumber": "1",
                                                      "mail": "bob@x", "check_at": clock.now + 24 * HOUR}
    assert client.get("/auth/session").get_json()["user"]["username"] == "alice"
    assert ldap.asked == [("lookup", "alice")]


def test_signing_out_forgets_the_details(alice):
    assert alice.post("/auth/logout").status_code == 200
    with alice.session_transaction() as session:
        assert user_management.LDAP_SESSION_KEY not in session
    assert alice.get("/api/containers").status_code == 401


def test_the_recheck_interval_is_configurable(app, alice, ldap, clock):
    app.config["LDAP_RECHECK_HOURS"] = 1
    alice.post("/auth/logout")
    alice.post("/auth/login", json={"username": "alice", "password": "pw"})
    ldap.asked.clear()
    clock.advance(hours=1.1)
    open_user_panel(alice)
    assert ldap.asked == [("lookup", "alice")]
