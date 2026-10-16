"""Characterization tests for ``compose_builder.build_compose_file``.

This is a pure function (no I/O, no app context), which makes it the safest
possible refactoring anchor. These tests pin the *current* observable
structure of the generated docker-compose document so that refactors of the
builder are caught the moment the output drifts.

Assertion style: we parse the generated YAML back with ``yaml.safe_load`` and
assert on the resulting structure rather than on raw text. The builder dumps
with ``default_style='"'`` (everything force-quoted), so we deliberately avoid
asserting on the *types* of bool/number fields after the round trip and assert
on string-valued fields and key presence instead.
"""

from pathlib import Path

import yaml
import pytest

from app.services.compose_builder import SHARED_IMAGE_ROLES, build_compose_file


def _build(**overrides):
    params = dict(
        container_name="alice-proj-1",
        role_name="worker_synced_ubuntu2404_ssh",
        user="alice",
        user_id=1000,
        group_id=1000,
        password="secret",
        project_name="proj",
        mac_address="AA:BB:CC:DD:EE:FF",
        network_name="testnet",
        ipv4_address="192.168.1.10",
    )
    params.update(overrides)
    return yaml.safe_load(build_compose_file(**params))


def _service(parsed):
    """The single service block, keyed by container_name."""
    return parsed["services"][parsed["name"]]


def test_top_level_structure():
    parsed = _build(container_name="alice-proj-1", network_name="testnet")
    assert parsed["name"] == "alice-proj-1"
    assert "alice-proj-1" in parsed["services"]
    assert "testnet" in parsed["networks"]
    # external flag is present (type intentionally not asserted; see module docstring)
    assert "external" in parsed["networks"]["testnet"]


def test_service_common_fields():
    svc = _service(_build())
    assert svc["container_name"] == "alice-proj-1"
    assert svc["runtime"] == "nvidia"
    assert "PROJECT=proj" in svc["environment"]
    assert "SAFE_PROJECT_NAME=proj" in svc["environment"]
    assert svc["networks"]["testnet"]["ipv4_address"] == "192.168.1.10"


def test_synced_mounts_project_dir_as_home():
    svc = _service(_build(role_name="worker_synced_ubuntu2404_ssh"))
    assert "/data/alice/proj/:/home/alice:rw" in svc["volumes"]


def test_local_mounts_local_home_and_synced():
    svc = _service(_build(role_name="worker_local_ubuntu2404_ssh"))
    assert "/home/alice/proj/:/home/alice:rw" in svc["volumes"]
    assert "/data/alice/proj/:/home/alice/synced:rw" in svc["volumes"]


# A role of the older kind, building an image per user: a custom one, kept in
# another directory of ANSIBLE_ROLES_PATH. All of WhaP's own share an image.
CUSTOM_ROLE = "worker_synced_custom_ssh"


def test_a_custom_role_builds_an_image_per_user():
    svc = _service(_build(role_name=CUSTOM_ROLE))
    assert "image" not in svc
    build = svc["build"]
    assert build["context"] == f"/docker/{CUSTOM_ROLE}-alice-proj/build/"
    assert build["dockerfile"] == "Dockerfile"
    assert build["args"]["USERNAME"] == "alice"
    assert build["args"]["USER_ID"] == "1000"
    assert build["args"]["GROUP_ID"] == "1000"
    assert build["args"]["PASSWORD"] == "secret"
    assert build["args"]["USER_COMMENT"] == "alice"


def test_a_custom_role_has_no_top_level_secrets():
    parsed = _build(role_name=CUSTOM_ROLE)
    assert "secrets" not in parsed


@pytest.mark.parametrize("role", sorted(SHARED_IMAGE_ROLES))
def test_shared_image_roles_run_their_tagged_image_with_the_user_as_environment(monkeypatch, role):
    monkeypatch.setenv("DOCKER_REGISTRY", "registry.example.com")
    parsed = _build(role_name=role, additional_gids=["15000", "15300"], image_tag="0123abcd4567",
                    password="Pa55-only-in-the-secret-file")
    svc = _service(parsed)
    assert "build" not in svc
    # One image per system, shared by its synced_ and local_ role.
    assert svc["image"] == f"registry.example.com/{role.split('_', 2)[2]}:0123abcd4567"
    # The user and the password reach the entrypoint at start, not the image.
    assert "USERNAME=alice" in svc["environment"]
    assert "USER_ID=1000" in svc["environment"]
    assert "GROUP_ID=1000" in svc["environment"]
    assert "PASSWORD_FILE=/run/secrets/user_password_file" in svc["environment"]
    assert "ADDITIONAL_GIDS=15000,15300" in svc["environment"]
    assert "Pa55-only-in-the-secret-file" not in yaml.safe_dump(parsed)
    # service-level secret reference
    assert svc["secrets"][0]["source"] == "user_password"
    assert svc["secrets"][0]["target"] == "user_password_file"
    # top-level secret definition
    assert parsed["secrets"]["user_password"]["file"] == "./secret_password.txt"


def test_image_name_without_registry(monkeypatch):
    monkeypatch.delenv("DOCKER_REGISTRY", raising=False)
    for role in ("worker_local_ubuntu2604_ssh", "worker_synced_ubuntu2604_ssh"):
        svc = _service(_build(role_name=role, image_tag="0123abcd4567"))
        assert svc["image"] == "ubuntu2604_ssh:0123abcd4567"


ROLES_DIR = Path(__file__).resolve().parents[3] / "roles"


def test_the_roles_that_provide_a_shared_image_are_the_ones_the_compose_builder_knows():
    """A role whose tasks provide a shared image (shared_image.yml) but which is missing
    from SHARED_IMAGE_ROLES would get a per-user build from WhaP, which nothing prepares."""
    shared = {d.name for d in ROLES_DIR.iterdir()
              if (d / "tasks" / "main.yml").exists() and "tasks_from: shared_image" in (d / "tasks" / "main.yml").read_text()}
    assert shared == SHARED_IMAGE_ROLES
    for role in shared:
        assert (ROLES_DIR / role / "tasks" / "build.yml").exists(), f"{role}: flask build-images runs tasks/build.yml"


def test_no_deploy_block_without_cpu_or_gpu():
    svc = _service(_build(cpu_limit=None, gpu_selection=()))
    assert "deploy" not in svc


def test_cpu_limit_adds_resource_limit():
    svc = _service(_build(cpu_limit=2.5))
    cpus = svc["deploy"]["resources"]["limits"]["cpus"]
    # value is force-quoted on dump; compare as string to stay type-agnostic
    assert str(cpus) == "2.5"


def test_gpu_selection_adds_reservation():
    svc = _service(_build(gpu_selection=["0", "1"]))
    device = svc["deploy"]["resources"]["reservations"]["devices"][0]
    assert device["driver"] == "nvidia"
    assert device["device_ids"] == ["0", "1"]
    assert device["capabilities"] == ["compute", "utility"]


def test_additional_volumes_are_appended():
    svc = _service(_build(additional_volumes=["/shared/ds:/home/alice/ds:ro"]))
    assert "/shared/ds:/home/alice/ds:ro" in svc["volumes"]


def test_role_name_must_have_two_underscores():
    """Characterizes the current input contract: ``role_name`` is split into
    exactly three parts, so a name with fewer underscores raises ValueError.
    """
    with pytest.raises(ValueError):
        build_compose_file(
            container_name="c",
            role_name="worker_synced",  # only one underscore
            user="alice",
            user_id=1000,
            group_id=1000,
            password="secret",
            project_name="proj",
            mac_address="AA:BB:CC:DD:EE:FF",
            network_name="testnet",
            ipv4_address="192.168.1.10",
        )
