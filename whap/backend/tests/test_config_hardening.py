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
import pytest
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


# --- ANSIBLE_RUNNER_DIR ---------------------------------------------------------
# Config never read it, so the startup check always warned, and ansible_service
# hard-coded <ANSIBLE_PROJECT_DIR>/ansible_runner regardless of the setting.

def test_runner_dir_is_read_and_made_absolute(monkeypatch, tmp_path):
    from app.config import _runner_dir
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANSIBLE_RUNNER_DIR", "runs")
    monkeypatch.setenv("ANSIBLE_PROJECT_DIR", "/backend")
    assert _runner_dir() == str(tmp_path / "runs")


def test_runner_dir_defaults_to_the_previous_hard_coded_path(monkeypatch):
    from app.config import _runner_dir
    monkeypatch.delenv("ANSIBLE_RUNNER_DIR", raising=False)
    monkeypatch.setenv("ANSIBLE_PROJECT_DIR", "/backend")
    assert _runner_dir() == "/backend/ansible_runner"


def test_runner_dir_is_unset_without_either(monkeypatch):
    from app.config import _runner_dir
    monkeypatch.delenv("ANSIBLE_RUNNER_DIR", raising=False)
    monkeypatch.delenv("ANSIBLE_PROJECT_DIR", raising=False)
    assert _runner_dir() is None


# --- ANSIBLE_ROLES_PATH is colon-separated ---------------------------------------

@pytest.fixture
def valid_config(monkeypatch, tmp_path):
    """A Config that passes check_critical_config; tests then break one thing."""
    from app import config
    for name, value in {"SECRET_KEY": "x" * 64, "CORS_ORIGINS": "https://whap.example",
                        "SQLALCHEMY_DATABASE_URI": "postgresql://db/whap", "REDIS_HOST": "redis",
                        "REDIS_PORT": "6379", "LDAP_SERVER_URI": "ldap://ldap", "LDAP_USER_BASE_DN": "dc=x",
                        "ANSIBLE_PROJECT_DIR": "/backend", "ANSIBLE_CONTAINER_BASE_DIR": "/docker",
                        "LDAP_TLS_OPTION": "DEMAND"}.items():
        monkeypatch.setattr(config.Config, name, value)
    return config


def test_a_colon_separated_roles_path_passes_the_startup_check(valid_config, monkeypatch, tmp_path, capsys):
    """Checked as one path, /backend/roles:/backend/roles_public failed every
    rebuilt backend at start-up."""
    (tmp_path / "roles").mkdir()
    (tmp_path / "public").mkdir()
    monkeypatch.setattr(valid_config.Config, "ANSIBLE_ROLES_PATH",
                        f"{tmp_path / 'roles'}:{tmp_path / 'extra'}:{tmp_path / 'public'}")
    valid_config.check_critical_config()
    assert "WARNING: ANSIBLE_ROLES_PATH entry" in capsys.readouterr().out  # the missing one is named


def test_a_failed_startup_check_stops_gunicorn_instead_of_hanging(valid_config, monkeypatch, tmp_path):
    """Exit code 3 is gunicorn's 'worker failed to boot', which stops the
    master. With 1 it respawned the worker forever and requests hung."""
    monkeypatch.setattr(valid_config.Config, "ANSIBLE_ROLES_PATH", str(tmp_path / "nowhere"))
    with pytest.raises(SystemExit) as exit_info:
        valid_config.check_critical_config()
    assert exit_info.value.code == 3
