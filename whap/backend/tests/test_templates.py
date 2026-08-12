import pytest
import os
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def template_env(request):
    # Set up Jinja2 environment to load from the roles directory.
    # roles/ lives at whap/roles (sibling of backend/); the worker_* roles each
    # build an image, so their docker-compose templates are what we render here.
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


def test_docker_compose_cpu_limit_rendering(template_env):
    env, roles_path = template_env

    # We will test one specific template
    template_path = 'worker_local_ubuntu2404_ssh/templates/docker-compose.yml.j2'
    if not os.path.exists(os.path.join(roles_path, template_path)):
        pytest.skip(f"Template {template_path} not found")

    # Due to 'lookup' usage in master template, we might need to test the specific file directly
    # The file path in FileSystemLoader should be relative to roles_path
    # But FileSystemLoader(roles_path) means we load by 'worker_.../templates/...'

    template = env.get_template(template_path)

    # Case 1: Unlimited (None)
    service_cfg = {
        'container_name': 'test-container',
        'project_name': 'test_project',
        'user': 'testuser',
        'user_id': 1000,
        'group_id': 1000,
        'password': 'password',
        'project': 'Test Project',
        'gpus': [],
        'mac_address': '00:00:00:00:00:00',
        'network': 'test-net',
        'ip_address': '192.168.1.10',
        'cpu_limit': None
    }

    output = template.render(service_cfg=service_cfg)
    assert 'cpus:' not in output

    # Case 2: Limited (float)
    service_cfg['cpu_limit'] = 2.5
    output = template.render(service_cfg=service_cfg)
    assert "cpus: '2.5'" in output

    # Check structure
    import yaml
    try:
        parsed = yaml.safe_load(output)
        resources = parsed['services']['test-container']['deploy']['resources']
        assert resources['limits']['cpus'] == '2.5'
    except Exception as e:
        pytest.fail(f"Generated YAML is invalid: {e}")

    # Case 3: Limited (int) - explicit test
    service_cfg['cpu_limit'] = 4
    output = template.render(service_cfg=service_cfg)
    assert "cpus: '4'" in output


def test_worker_synced_schema_correctness(template_env):
    """
    Test the refactored worker_synced_ubuntu2504_ssh template to ensure
    it generates valid YAML using the structured dictionary approach.
    """
    env, roles_path = template_env
    template_path = 'worker_synced_ubuntu2504_ssh/templates/docker-compose.yml.j2'

    if not os.path.exists(os.path.join(roles_path, template_path)):
        pytest.skip(f"Template {template_path} not found")

    template = env.get_template(template_path)

    service_cfg = {
        'container_name': 'pina-testproj-1',
        'user': 'pina',
        'project_name': 'testproj',
        'user_id': 1000,
        'group_id': 1000,
        'password': 'REDACTED',
        'project': 'testproj',
        'gpus': ['0'],
        'mac_address': 'AA:BB:CC:DD:EE:FF',
        'network': 'Test Network',
        'ip_address': '192.168.1.50',
        'cpu_limit': 1.0,
        'additional_volumes': ['/extra:/extra:rw']
    }

    output = template.render(service_cfg=service_cfg)

    # 1. basic string assertions
    assert "cpus: '1.0'" in output
    assert "name: pina-testproj-1" in output

    # 2. Strict YAML parsing
    import yaml
    try:
        parsed = yaml.safe_load(output)
    except yaml.YAMLError as e:
        pytest.fail(f"Refactored template generated invalid YAML: {e}")

    # 3. Logic checks
    service = parsed['services']['pina-testproj-1']
    deploy = service['deploy']

    # Check CPU limit
    assert deploy['resources']['limits']['cpus'] == '1.0'

    # Check GPU device_ids - this was the main source of the bug (invalid list syntax)
    device_reservation = deploy['resources']['reservations']['devices'][0]
    assert device_reservation['device_ids'] == ['0']

    # Check additional volumes
    assert '/extra:/extra:rw' in service['volumes']
