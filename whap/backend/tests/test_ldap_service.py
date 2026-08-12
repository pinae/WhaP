"""Tests for app.services.ldap_service.

WhalePond authenticates against a single LDAP access group, "ccs-srv", which RUB
models as an OU. ``LDAP_USER_BASE_DN`` points at that OU's subtree, so listing the
rubPersons under it yields exactly the group's members. (This LDAP group is
distinct from WhalePond's *internal* groups, which govern resource/image
permissions and never touch LDAP.)

``get_all_users_in_group`` must therefore search under the configured base DN
with a person filter -- not a narrower/other base, and not a memberOf filter
(person entries under an OU don't link back to it via memberOf).

The fake LDAP module is deliberately tolerant of how the filter is built: it
supplies ``filter.filter_format`` so the test passes whether the implementation
uses ``ldap.filter.filter_format("(objectClass=rubPerson)", [])`` or a plain
string. The test pins behaviour (scope + returned members), not that detail.
"""


class _FakeLdapConn:
    def __init__(self, recorder):
        object.__setattr__(self, "_recorder", recorder)

    def set_option(self, *a, **k):
        pass

    def simple_bind_s(self, *a, **k):
        return True

    def search_s(self, base_dn, scope, search_filter, attrs):
        self._recorder["base_dn"] = base_dn
        self._recorder["filter"] = search_filter
        # Two ccs-srv members; the second omits 'mail' to exercise the optional path.
        return [
            ("uid=jdoe,ou=ccs-srv,ou=hosts,dc=x",
             {"uid": [b"jdoe"], "cn": [b"Jane Doe"], "mail": [b"jane@x"]}),
            ("uid=asmith,ou=ccs-srv,ou=hosts,dc=x",
             {"uid": [b"asmith"], "cn": [b"Al Smith"]}),
        ]

    def unbind_s(self):
        pass


class _FakeLdapFilter:
    @staticmethod
    def filter_format(fmt, args):
        return fmt % tuple(args) if args else fmt


def _make_fake_ldap(recorder):
    class _FakeLdapModule:
        SCOPE_SUBTREE = 2
        VERSION3 = 3
        OPT_REFERRALS = 8
        OPT_X_TLS_REQUIRE_CERT = 0
        OPT_X_TLS_DEMAND = 2
        OPT_X_TLS_ALLOW = 3
        LDAPError = Exception
        filter = _FakeLdapFilter

        @staticmethod
        def set_option(*a, **k):
            pass

        @staticmethod
        def initialize(uri):
            return _FakeLdapConn(recorder)

    return _FakeLdapModule


def test_group_search_scoped_to_ccs_srv_base_dn(app, monkeypatch):
    import app.services.ldap_service as ldap_service

    recorder = {}
    base = "ou=ccs-srv,ou=hosts,dc=ruhr-uni-bochum,dc=de"
    monkeypatch.setattr(ldap_service, "ldap", _make_fake_ldap(recorder))

    with app.app_context():
        app.config["LDAP_SERVER_URI"] = "ldaps://ldap.example.com:636"
        app.config["LDAP_USER_BASE_DN"] = base
        app.config["LDAP_BIND_USER"] = "cn=svc,dc=x"
        app.config["LDAP_BIND_PASSWORD"] = "secret"
        result = ldap_service.get_all_users_in_group()

    # Searched under the ccs-srv subtree with a person filter.
    assert recorder["base_dn"] == base
    assert "objectClass=rubPerson" in recorder["filter"]
    # Mapped both returned members; missing mail tolerated.
    assert {u["uid"] for u in result} == {"jdoe", "asmith"}
    assert next(u for u in result if u["uid"] == "jdoe")["full_name"] == "Jane Doe"


def test_group_search_returns_none_on_incomplete_config(app, monkeypatch):
    import app.services.ldap_service as ldap_service

    recorder = {}
    monkeypatch.setattr(ldap_service, "ldap", _make_fake_ldap(recorder))

    with app.app_context():
        app.config["LDAP_SERVER_URI"] = "ldaps://ldap.example.com:636"
        app.config["LDAP_USER_BASE_DN"] = None  # missing -> fail closed
        app.config["LDAP_BIND_USER"] = "cn=svc,dc=x"
        app.config["LDAP_BIND_PASSWORD"] = "secret"
        result = ldap_service.get_all_users_in_group()

    assert result is None
    assert "base_dn" not in recorder  # no search attempted
