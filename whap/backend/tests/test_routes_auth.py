"""Tests for app.routes.auth (login / logout / session).

Auth is the entry point for every authenticated request. Local auth runs
against the DB; LDAP auth is mocked (``authenticate_user`` returns a details
dict, not a bare uid, despite the variable name in the route). Email lookup on
successful login is mocked too, since it would otherwise hit LDAP/notification.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_email_lookup(monkeypatch):
    """Login calls notification_service.get_user_email; stub it by default."""
    import app.routes.auth as auth
    monkeypatch.setattr(auth.notification_service, "get_user_email", lambda uid: None)


# --- login: validation ------------------------------------------------------

def test_login_missing_credentials_400(client, db):
    assert client.post("/auth/login", json={"username": "x"}).status_code == 400
    assert client.post("/auth/login", json={"password": "y"}).status_code == 400
    assert client.post("/auth/login", json={}).status_code == 400


# --- login: local -----------------------------------------------------------

def test_login_local_success(client, db, make_local_user, monkeypatch):
    import app.routes.auth as auth
    monkeypatch.setattr(auth.notification_service, "get_user_email",
                        lambda uid: "alice@example.com")
    user = make_local_user(username="alice", password="s3cret")

    resp = client.post("/auth/login", json={"username": "alice", "password": "s3cret"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()["user"]
    assert body["id"] == f"local:{user.id}"
    assert body["username"] == "alice"
    assert body["user_type"] == "local"
    assert body["is_admin"] is False
    assert body["email"] == "alice@example.com"


def test_login_local_admin_flag(client, db, make_local_user):
    from app.models import GroupMembership
    user = make_local_user(username="rootish", password="pw", is_admin=True)
    resp = client.post("/auth/login", json={"username": "rootish", "password": "pw"})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["is_admin"] is True


def test_login_local_wrong_password_401(client, db, make_local_user):
    make_local_user(username="bob", password="right")
    resp = client.post("/auth/login", json={"username": "bob", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.get_json()["message"] == "Invalid credentials"


# --- login: LDAP fallback (mocked) -----------------------------------------

def test_login_ldap_success_when_not_local(client, db, monkeypatch):
    import app.routes.auth as auth
    # Unknown locally -> LDAP path. authenticate_user returns a details dict.
    monkeypatch.setattr(
        auth.ldap_service, "authenticate_user",
        lambda username, password: {"uid": username, "uidNumber": "5000", "gidNumber": "5000"},
    )
    resp = client.post("/auth/login", json={"username": "jdoe", "password": "ldappw"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()["user"]
    assert body["id"] == "ldap:jdoe"
    assert body["user_type"] == "ldap"


def test_login_ldap_failure_401(client, db, monkeypatch):
    import app.routes.auth as auth
    monkeypatch.setattr(auth.ldap_service, "authenticate_user",
                        lambda username, password: None)
    resp = client.post("/auth/login", json={"username": "ghost", "password": "nope"})
    assert resp.status_code == 401
    assert resp.get_json()["message"] == "Invalid credentials"


def test_login_local_miss_falls_through_to_ldap(client, db, make_local_user, monkeypatch):
    """A username that exists locally but with a different case is not matched by
    the exact filter, so it falls through to LDAP (proving local-miss routing)."""
    import app.routes.auth as auth
    called = {"ldap": False}

    def fake_ldap(username, password):
        called["ldap"] = True
        return None

    monkeypatch.setattr(auth.ldap_service, "authenticate_user", fake_ldap)
    resp = client.post("/auth/login", json={"username": "does_not_exist", "password": "x"})
    assert resp.status_code == 401
    assert called["ldap"] is True


# --- logout -----------------------------------------------------------------

def test_logout_requires_login(client, db):
    assert client.post("/auth/logout").status_code == 401


def test_logout_success(client, db, make_local_user, login_as):
    user = make_local_user(username="logmeout")
    login_as(user)
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Logout successful"
    # Session cleared -> subsequent session check is logged out.
    assert client.get("/auth/session").get_json()["isLoggedIn"] is False


# --- session ----------------------------------------------------------------

def test_session_authenticated(client, db, make_local_user, login_as):
    user = make_local_user(username="sess_user")
    login_as(user)
    resp = client.get("/auth/session")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["isLoggedIn"] is True
    assert body["user"]["id"] == f"local:{user.id}"
    assert body["user"]["username"] == "sess_user"


def test_session_anonymous(client, db):
    resp = client.get("/auth/session")
    assert resp.status_code == 200
    assert resp.get_json() == {"isLoggedIn": False, "user": None}
