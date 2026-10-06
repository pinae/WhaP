"""Tests for app.services.ldap_service.

WhalePond authenticates against a single LDAP access group, "ccs-srv", which RUB
models as an OU. ``LDAP_USER_BASE_DN`` points at that OU's subtree, so listing the
persons under it yields exactly the group's members. (This LDAP group is
distinct from WhalePond's *internal* groups, which govern resource/image
permissions and never touch LDAP.)

``get_all_users_in_group`` must therefore search under the configured base DN
with a person filter -- not a narrower/other base, and not a memberOf filter
(person entries under an OU don't link back to it via memberOf).

The fake LDAP module records every connection and the options set on it. Its
module-level ``set_option`` raises: TLS settings applied there are
process-global and leak between requests, which is the bug these tests pin.
"""
import pytest

PERSON_ENTRIES = [
    ("uid=jdoe,ou=ccs-srv,ou=hosts,dc=x",
     {"uid": [b"jdoe"], "cn": [b"Jane Doe"], "mail": [b"jane@x"],
      "uidNumber": [b"5001"], "gidNumber": [b"5000"]}),
    ("uid=asmith,ou=ccs-srv,ou=hosts,dc=x",
     {"uid": [b"asmith"], "cn": [b"Al Smith"],
      "uidNumber": [b"5002"], "gidNumber": [b"5000"]}),
]


class _InvalidCredentials(Exception):
    pass


class _FakeLdapConn:
    def __init__(self, module, uri):
        self.module = module
        self.uri = uri
        self.options = []  # (option, value) in the order they were set
        self.bound_as = None
        module.connections.append(self)

    def set_option(self, option, value):
        self.options.append((option, value))

    def simple_bind_s(self, who, password):
        if password in self.module.bad_passwords:
            raise _InvalidCredentials()
        self.bound_as = who

    def search_s(self, base_dn, scope, search_filter, attrs):
        self.module.searches.append({"base_dn": base_dn, "filter": search_filter})
        if search_filter.startswith("(uid="):
            uid = search_filter[len("(uid="):-1]
            return [e for e in PERSON_ENTRIES if e[1]["uid"][0].decode() == uid]
        return PERSON_ENTRIES

    def unbind_s(self):
        pass


class _FakeLdapFilter:
    @staticmethod
    def filter_format(fmt, args):
        return fmt % tuple(args) if args else fmt


class _FakeLdapModule:
    SCOPE_SUBTREE = 2
    VERSION3 = 3
    OPT_REFERRALS = 8
    OPT_X_TLS_REQUIRE_CERT = 24582
    OPT_X_TLS_NEVER = 0  # falsy in real python-ldap too
    OPT_X_TLS_DEMAND = 2
    OPT_X_TLS_ALLOW = 3
    OPT_X_TLS_CACERTFILE = 24578
    OPT_X_TLS_NEWCTX = 24591
    LDAPError = Exception
    INVALID_CREDENTIALS = _InvalidCredentials
    filter = _FakeLdapFilter

    def __init__(self):
        self.connections = []
        self.searches = []
        self.bad_passwords = set()

    @staticmethod
    def set_option(*a, **k):
        raise AssertionError("module-level ldap.set_option is process-global; set options per connection")

    def initialize(self, uri):
        return _FakeLdapConn(self, uri)


@pytest.fixture
def fake_ldap(app, monkeypatch):
    import app.services.ldap_service as ldap_service
    module = _FakeLdapModule()
    monkeypatch.setattr(ldap_service, "ldap", module)
    app.config.update(
        LDAP_SERVER_URI="ldaps://ldap.example.com:636",
        LDAP_USER_BASE_DN="ou=ccs-srv,ou=hosts,dc=ruhr-uni-bochum,dc=de",
        LDAP_BIND_USER="cn=svc,dc=x",
        LDAP_BIND_PASSWORD="secret",
        LDAP_TLS_OPTION="DEMAND",
        LDAP_CA_CERT_FILE=None,
        LDAP_USER_OBJECT_CLASS="rubPerson",
    )
    return module


def _tls_value(conn):
    return dict(conn.options)[_FakeLdapModule.OPT_X_TLS_REQUIRE_CERT]


# --- group listing ----------------------------------------------------------

def test_group_search_scoped_to_ccs_srv_base_dn(app, fake_ldap):
    from app.services import ldap_service
    result = ldap_service.get_all_users_in_group()

    # Searched under the ccs-srv subtree with a person filter.
    assert fake_ldap.searches[0]["base_dn"] == app.config["LDAP_USER_BASE_DN"]
    assert fake_ldap.searches[0]["filter"] == "(objectClass=rubPerson)"
    # Mapped both returned members; missing mail tolerated.
    assert {u["uid"] for u in result} == {"jdoe", "asmith"}
    assert next(u for u in result if u["uid"] == "jdoe")["full_name"] == "Jane Doe"
    assert next(u for u in result if u["uid"] == "asmith")["mail"] is None


def test_group_search_object_class_is_configurable(app, fake_ldap):
    """A stock OpenLDAP (e.g. the e2e test directory) has no rubPerson class."""
    from app.services import ldap_service
    app.config["LDAP_USER_OBJECT_CLASS"] = "inetOrgPerson"
    ldap_service.get_all_users_in_group()
    assert fake_ldap.searches[0]["filter"] == "(objectClass=inetOrgPerson)"


def test_group_search_returns_none_on_incomplete_config(app, fake_ldap):
    from app.services import ldap_service
    app.config["LDAP_USER_BASE_DN"] = None  # missing -> fail closed
    assert ldap_service.get_all_users_in_group() is None
    assert fake_ldap.connections == []  # no connection attempted


# --- TLS options are per connection -----------------------------------------

@pytest.mark.parametrize("setting, expected", [
    ("DEMAND", _FakeLdapModule.OPT_X_TLS_DEMAND),
    ("ALLOW", _FakeLdapModule.OPT_X_TLS_ALLOW),
    ("NEVER", _FakeLdapModule.OPT_X_TLS_NEVER),
    ("never", _FakeLdapModule.OPT_X_TLS_NEVER),  # case-insensitive
])
def test_tls_option_is_applied_to_the_connection(app, fake_ldap, setting, expected):
    """Every value takes effect -- NEVER used to fall through and do nothing --
    and it lands on the connection, not process-wide (the fake raises on that)."""
    from app.services import ldap_service
    app.config["LDAP_TLS_OPTION"] = setting
    ldap_service.get_ldap_user_details("jdoe")

    conn = fake_ldap.connections[0]
    assert _tls_value(conn) == expected


def test_new_tls_context_is_created_last(app, fake_ldap):
    """Per-connection TLS settings are ignored until OPT_X_TLS_NEWCTX."""
    from app.services import ldap_service
    app.config["LDAP_CA_CERT_FILE"] = "/etc/ssl/private-ca.pem"
    ldap_service.get_ldap_user_details("jdoe")

    options = [option for option, _ in fake_ldap.connections[0].options]
    assert options[-1] == _FakeLdapModule.OPT_X_TLS_NEWCTX
    assert options.index(_FakeLdapModule.OPT_X_TLS_REQUIRE_CERT) < options.index(_FakeLdapModule.OPT_X_TLS_NEWCTX)


def test_ca_cert_file_is_applied_when_configured(app, fake_ldap):
    from app.services import ldap_service
    app.config["LDAP_CA_CERT_FILE"] = "/etc/ssl/private-ca.pem"
    ldap_service.get_ldap_user_details("jdoe")
    assert dict(fake_ldap.connections[0].options)[_FakeLdapModule.OPT_X_TLS_CACERTFILE] == "/etc/ssl/private-ca.pem"


def test_ca_cert_file_is_not_set_when_absent(app, fake_ldap):
    from app.services import ldap_service
    ldap_service.get_ldap_user_details("jdoe")
    assert _FakeLdapModule.OPT_X_TLS_CACERTFILE not in dict(fake_ldap.connections[0].options)


def test_settings_do_not_leak_between_connections(app, fake_ldap):
    """Each connection carries its own setting; a later one isn't affected by an earlier one."""
    from app.services import ldap_service
    app.config["LDAP_TLS_OPTION"] = "NEVER"
    ldap_service.get_ldap_user_details("jdoe")
    app.config["LDAP_TLS_OPTION"] = "DEMAND"
    ldap_service.get_ldap_user_details("jdoe")

    first, second = fake_ldap.connections
    assert _tls_value(first) == _FakeLdapModule.OPT_X_TLS_NEVER
    assert _tls_value(second) == _FakeLdapModule.OPT_X_TLS_DEMAND


@pytest.mark.parametrize("call", [
    lambda s: s.get_ldap_user_details("jdoe"),
    lambda s: s.get_all_users_in_group(),
    lambda s: s.authenticate_user("jdoe", "pw"),
])
def test_unknown_tls_option_fails_closed_without_connecting(app, fake_ldap, call):
    from app.services import ldap_service
    app.config["LDAP_TLS_OPTION"] = "SOMETIMES"
    assert call(ldap_service) is None
    assert fake_ldap.connections == []


# --- authenticate_user ------------------------------------------------------

def test_authenticate_verifies_password_as_the_found_dn(app, fake_ldap):
    from app.services import ldap_service
    details = ldap_service.authenticate_user("jdoe", "users-password")

    assert details == {"uid": "jdoe", "uidNumber": "5001", "gidNumber": "5000", "mail": "jane@x"}
    service_conn, user_conn = fake_ldap.connections
    assert service_conn.bound_as == "cn=svc,dc=x"
    assert user_conn.bound_as == "uid=jdoe,ou=ccs-srv,ou=hosts,dc=x"
    # The password check runs on a connection with the same TLS settings.
    assert _tls_value(user_conn) == _FakeLdapModule.OPT_X_TLS_DEMAND


def test_authenticate_tolerates_missing_mail(app, fake_ldap):
    from app.services import ldap_service
    assert ldap_service.authenticate_user("asmith", "pw")["mail"] is None


def test_authenticate_wrong_password_returns_none(app, fake_ldap):
    from app.services import ldap_service
    fake_ldap.bad_passwords.add("wrong")
    assert ldap_service.authenticate_user("jdoe", "wrong") is None


def test_authenticate_unknown_user_returns_none(app, fake_ldap):
    from app.services import ldap_service
    assert ldap_service.authenticate_user("nobody", "pw") is None
    assert len(fake_ldap.connections) == 1  # never attempted a user bind


# --- configuration check ----------------------------------------------------

@pytest.mark.parametrize("value", ["DEMAND", "ALLOW", "NEVER", "never", None])
def test_config_accepts_valid_tls_options(value):
    from types import SimpleNamespace
    from app.config import find_config_problems
    cfg = SimpleNamespace(SECRET_KEY="k", CORS_ORIGINS="http://x", LDAP_TLS_OPTION=value)
    assert find_config_problems(cfg) == []


def test_config_rejects_unknown_tls_option():
    from types import SimpleNamespace
    from app.config import find_config_problems
    cfg = SimpleNamespace(SECRET_KEY="k", CORS_ORIGINS="http://x", LDAP_TLS_OPTION="SOMETIMES")
    assert any("LDAP_TLS_OPTION" in p for p in find_config_problems(cfg))
