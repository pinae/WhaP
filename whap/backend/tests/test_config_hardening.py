"""WP3 - fail-closed configuration & secret hardening.

The app used to fall back to a hardcoded ``SECRET_KEY`` (session forgery ->
admin takeover), default LDAP TLS to ``ALLOW`` (accepts bad certs -> MITM of the
bind password), and ship with session-cookie hardening commented out.

Two kinds of test here:

* Pure-predicate tests build throwaway config-like objects and assert
  ``find_config_problems`` flags the insecure ones. These don't touch the
  environment or the on-disk ``.env`` at all.
* Code-default tests reload ``app.config`` with the relevant variables removed
  from the environment, so they assert the *in-source* defaults rather than
  whatever a developer's ``.env`` happens to contain.
"""
import importlib
from types import SimpleNamespace


# --- Pure predicate: find_config_problems ---------------------------------

def _cfg(**overrides):
    base = dict(SECRET_KEY="a-strong-random-value", CORS_ORIGINS="http://localhost:3000")
    base.update(overrides)
    return SimpleNamespace(**base)


def test_missing_secret_key_is_rejected():
    from app.config import find_config_problems
    problems = find_config_problems(_cfg(SECRET_KEY=None))
    assert any("SECRET_KEY" in p for p in problems)


def test_default_secret_key_is_rejected():
    from app.config import find_config_problems, INSECURE_SECRET_KEY
    problems = find_config_problems(_cfg(SECRET_KEY=INSECURE_SECRET_KEY))
    assert any("SECRET_KEY" in p for p in problems)


def test_strong_secret_key_is_accepted():
    from app.config import find_config_problems
    assert find_config_problems(_cfg()) == []


def test_cors_wildcard_with_credentials_rejected():
    from app.config import find_config_problems
    problems = find_config_problems(_cfg(CORS_ORIGINS="*"))
    assert any("CORS" in p for p in problems)


def test_cors_wildcard_among_origins_rejected():
    from app.config import find_config_problems
    problems = find_config_problems(_cfg(CORS_ORIGINS="http://localhost:3000,*"))
    assert any("CORS" in p for p in problems)


# --- Code defaults (env-independent via reload) ----------------------------

def _reload_config_without(monkeypatch, *env_vars):
    """Reload app.config with the given env vars removed, so class attributes
    reflect the in-source defaults rather than the ambient environment/.env.

    Neutralises ``dotenv.load_dotenv`` *at its source* so that the reloaded
    module's top-level ``from dotenv import load_dotenv`` picks up the no-op and
    a developer's on-disk .env can't repopulate the variables during reload.
    """
    import dotenv
    import app.config as config_module
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    return importlib.reload(config_module)


def test_ldap_tls_defaults_to_demand(monkeypatch):
    config_module = _reload_config_without(monkeypatch, "LDAP_TLS_OPTION")
    try:
        assert config_module.Config.LDAP_TLS_OPTION == "DEMAND"
    finally:
        _reload_config_without(monkeypatch)  # restore module to ambient env


def test_session_cookie_flags_secure_by_default(monkeypatch):
    config_module = _reload_config_without(
        monkeypatch,
        "SESSION_COOKIE_SECURE",
        "SESSION_COOKIE_HTTPONLY",
        "SESSION_COOKIE_SAMESITE",
    )
    try:
        cfg = config_module.Config
        assert cfg.SESSION_COOKIE_HTTPONLY is True
        assert cfg.SESSION_COOKIE_SECURE is True
        assert cfg.SESSION_COOKIE_SAMESITE in ("Lax", "Strict")
    finally:
        _reload_config_without(monkeypatch)


# --- Auth round-trip guard -------------------------------------------------

def test_login_cookie_round_trips_under_test_config(app, make_local_user):
    """A real /auth/login must set a session cookie the client resends on the
    next request. This pins that the cookie flags used in tests don't silently
    break session reuse (and that the auth path itself works end to end).
    """
    make_local_user(username="rt_user", password="password123")
    c = app.test_client()

    login = c.post("/auth/login", json={"username": "rt_user", "password": "password123"})
    assert login.status_code == 200, login.get_data(as_text=True)

    session = c.get("/auth/session")
    assert session.status_code == 200
    body = session.get_json()
    assert body["isLoggedIn"] is True
    assert body["user"]["username"] == "rt_user"
