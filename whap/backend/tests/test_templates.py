import pytest
import os
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def template_env(request):
    # Set up Jinja2 environment to load from the roles directory (roles/ at the
    # repository root). The worker roles' compose files are WhaP's
    # (compose_builder, tested there); here: the whap role's templates.
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, '..', '..', '..', 'roles'),  # roles
    ]
    roles_path = next((os.path.abspath(p) for p in candidates if os.path.isdir(p)), None)
    if roles_path is None:
        pytest.skip("Roles directory not found (looked in roles/)")

    loader = FileSystemLoader(roles_path)
    env = Environment(loader=loader)

    # helper filter
    def to_yaml(value):
        import yaml
        return yaml.dump(value, default_flow_style=False).strip()

    def to_nice_yaml(value, indent=2):
        import yaml
        return yaml.dump(value, default_flow_style=False, indent=indent)

    def to_json(value):
        import json
        return json.dumps(value)

    env.filters['to_yaml'] = to_yaml
    env.filters['to_nice_yaml'] = to_nice_yaml
    env.filters['to_json'] = to_json

    return env, roles_path


def _render_env(template_env, notifications=None, e2e=False):
    env, _ = template_env
    service_cfg = {
        "secret_key": "x" * 64, "domain": "whap.example.org", "container_file_owner": "pina",
        "db": {"user": "u", "password": "p", "name": "whap"},
        "influxdb": {"token": "t", "org": "o", "bucket": "b"},
    }
    if notifications is not None:
        service_cfg["notifications"] = notifications
    if e2e:
        service_cfg["e2e"] = {"enabled": True}
    rendered = env.get_template("whap/templates/env.prod.j2").render(
        service_cfg=service_cfg, docker_dir="/docker",
        ldap={"uri": "ldaps://ldap", "base": {"dn": "dc=x"}, "binduser": {"dn": "cn=b", "password": "pw"}})
    values = {}
    for line in rendered.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'")
    return values


def test_without_notification_settings_whap_sends_no_email(template_env):
    values = _render_env(template_env)
    assert values["WHAP_URL"] == "https://whap.example.org"
    assert values["TTL_REMINDER_DAYS"] == "7,1"
    assert values["TIMEZONE"] == "UTC"
    assert not {"SMTP_SERVER", "SENDER_EMAIL", "MATRIX_HOMESERVER_URL", "MATRIX_ACCESS_TOKEN"} & set(values)


def test_notification_settings_reach_the_backend_in_a_form_it_accepts(template_env):
    from types import SimpleNamespace
    from app.config import find_config_problems, reminder_days

    values = _render_env(template_env, {
        "ttl_reminder_days": [14, 7, 1],
        "smtp": {"server": "smtp.example.org", "port": 465, "security": "ssl", "username": "whap",
                 "password": "pw", "sender": "whap@example.org"},
        "matrix": {"homeserver_url": "https://matrix.example.org", "access_token": "syt_x",
                   "user_domain": "example.org"},
    })
    assert values["SMTP_PORT"] == "465" and values["SENDER_NAME"] == "WhaP"
    assert values["MATRIX_USER_DOMAIN"] == "example.org"
    assert reminder_days(values["TTL_REMINDER_DAYS"]) == [14, 7, 1]
    assert find_config_problems(SimpleNamespace(**values)) == []


def test_an_smtp_relay_without_login_gets_no_credentials(template_env):
    values = _render_env(template_env, {"smtp": {"server": "relay.example.org", "security": "none",
                                                 "port": 25, "sender": "whap@example.org"}})
    assert "SMTP_USERNAME" not in values and "SMTP_PASSWORD" not in values
    assert values["SMTP_SECURITY"] == "none"


def test_a_test_rig_mails_only_to_its_mail_catcher_and_has_no_matrix(template_env):
    from types import SimpleNamespace
    from app.config import find_config_problems

    values = _render_env(template_env, {
        "smtp": {"server": "smtp.example.org", "sender": "whap@example.org"},
        "matrix": {"homeserver_url": "https://matrix.example.org", "access_token": "syt_x"},
    }, e2e=True)
    assert (values["SMTP_SERVER"], values["SMTP_PORT"], values["SMTP_SECURITY"]) == ("e2e-mailpit", "1025", "none")
    assert "MATRIX_HOMESERVER_URL" not in values and "MATRIX_ACCESS_TOKEN" not in values
    assert find_config_problems(SimpleNamespace(**values)) == []
