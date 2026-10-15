"""Shared images: their tags, and `flask build-images`.

A role's image tag is a hash of the files it is built from, so the same files
give the same image everywhere (a test rig's build is production's), and a
change gives a new one instead of replacing an image under a name in use.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.services.images import BUILD_FILES, image_tag, role_dir

ROLES_DIR = Path(__file__).resolve().parents[3] / "roles"


def make_role(base, name="worker_synced_test_ssh", dockerfile="FROM ubuntu:26.04\n"):
    role = base / name
    (role / "templates").mkdir(parents=True)
    (role / "files").mkdir()
    (role / "tasks").mkdir()
    (role / "templates" / "Dockerfile.j2").write_text(dockerfile)
    (role / "files" / "entrypoint.sh").write_text("#!/bin/bash\n")
    (role / "files" / "nopasswd").write_text("%sudo ALL=(ALL:ALL) NOPASSWD:ALL")
    return role


# --- the tag ---------------------------------------------------------------------

def test_the_same_files_give_the_same_tag_wherever_they_are(tmp_path):
    make_role(tmp_path / "a")
    make_role(tmp_path / "b")
    assert image_tag("worker_synced_test_ssh", str(tmp_path / "a")) == \
        image_tag("worker_synced_test_ssh", str(tmp_path / "b"))


@pytest.mark.parametrize("changed", BUILD_FILES)
def test_a_change_to_any_build_file_is_a_new_tag(tmp_path, changed):
    role = make_role(tmp_path)
    before = image_tag(role.name, str(tmp_path))
    (role / changed).write_text((role / changed).read_text() + "# changed\n")
    assert image_tag(role.name, str(tmp_path)) != before


def test_other_files_of_the_role_do_not_change_the_tag(tmp_path):
    """bashrc, profile and the tasks are not in the image."""
    role = make_role(tmp_path)
    before = image_tag(role.name, str(tmp_path))
    (role / "files" / "bashrc").write_text("alias ll='ls -l'\n")
    (role / "tasks" / "main.yml").write_text("- debug: {}\n")
    assert image_tag(role.name, str(tmp_path)) == before


def test_the_role_is_found_as_ansible_finds_it(tmp_path):
    """ANSIBLE_ROLES_PATH is searched in order: a role in an earlier directory hides one in a later."""
    make_role(tmp_path / "private", dockerfile="FROM ubuntu:24.04\n")
    make_role(tmp_path / "public")
    path = f"{tmp_path / 'private'}:{tmp_path / 'public'}"
    assert role_dir("worker_synced_test_ssh", path) == str(tmp_path / "private" / "worker_synced_test_ssh")
    assert image_tag("worker_synced_test_ssh", path) == image_tag("worker_synced_test_ssh", str(tmp_path / "private"))


def test_a_role_that_is_not_here_is_latest(tmp_path):
    assert image_tag("worker_missing", str(tmp_path)) == "latest"


def test_each_system_has_its_own_tag():
    """synced_ and local_ of a system are built from the same files: the same tag, under
    two names (the second build comes from the layer cache). Systems differ."""
    tags = {role.name: image_tag(role.name, str(ROLES_DIR))
            for role in ROLES_DIR.iterdir() if (role / "templates" / "Dockerfile.j2").exists()}
    assert all(len(tag) == 12 for tag in tags.values())
    assert tags["worker_synced_ubuntu2604_ssh"] == tags["worker_local_ubuntu2604_ssh"]
    by_system = {}
    for role, tag in tags.items():
        by_system.setdefault(role.split("_", 2)[2], set()).add(tag)
    assert all(len(system_tags) == 1 for system_tags in by_system.values())
    assert len({tag for system_tags in by_system.values() for tag in system_tags}) == len(by_system)


def test_the_build_files_are_the_ones_the_role_copies():
    """shared_image.yml copies these to the build directory; a file it copies but
    the tag ignores would change the image without changing its name."""
    tasks = yaml.safe_load((ROLES_DIR / "common_tasks" / "tasks" / "shared_image.yml").read_text())
    build = next(t for t in tasks[0]["block"] if t["name"].startswith("Build"))
    copied = next(t for t in build["block"] if "ansible.builtin.copy" in t)["loop"]
    assert {f"files/{name}" for name in copied} | {"templates/Dockerfile.j2"} == set(BUILD_FILES)


# --- flask build-images --------------------------------------------------------------

@pytest.fixture
def builds(app, monkeypatch, tmp_path):
    """Runs of ansible-runner: the playbook each was given and the inventory files present then."""
    import app.image_builds as image_builds
    app.config["ANSIBLE_ROLES_PATH"] = str(ROLES_DIR)
    app.config["DOCKER_REGISTRY"] = "registry.example.org"
    runs = []

    def run(**config):
        inventory = Path(config["inventory"])
        runs.append({"playbook": yaml.safe_load(Path(config["playbook"]).read_text()),
                     "hosts_files": sorted(p.name for p in inventory.glob("99_dynamic_hosts_job_*")),
                     "quiet": config["quiet"]})
        return SimpleNamespace(status=runs[-1].get("status", "successful"), rc=0)

    monkeypatch.setattr(image_builds.ansible_runner, "run", run)
    return runs


def test_build_images_builds_every_shared_image_on_the_server(app, db, builds, make_server):
    from app.services.compose_builder import SHARED_IMAGE_ROLES
    make_server(hostname="tycho")
    result = app.test_cli_runner().invoke(args=["build-images", "--server", "tycho"])
    assert result.exit_code == 0, result.output
    [run] = builds
    [play] = run["playbook"]
    assert play["hosts"] == "tycho"
    roles = [task["ansible.builtin.include_role"]["name"] for task in play["tasks"]]
    assert sorted(roles) == sorted(SHARED_IMAGE_ROLES)
    for task in play["tasks"]:
        role = task["ansible.builtin.include_role"]["name"]
        assert task["ansible.builtin.include_role"]["tasks_from"] == "build"
        assert task["vars"]["service_cfg"] == {"image_name": role, "whap_registry": "registry.example.org",
                                               "image_tag": image_tag(role)}
        assert f"registry.example.org/{role.removeprefix('worker_')}:{image_tag(role)}" in result.output
    assert len(run["hosts_files"]) == 1 and not run["quiet"]
    inventory = Path(app.config["ANSIBLE_PROJECT_DIR"]) / "inventory"
    assert not list(inventory.glob("99_dynamic_hosts_job_images_*")), "the run's host file is removed"


def test_build_images_builds_the_roles_named(app, db, builds, make_server):
    make_server(hostname="tycho")
    result = app.test_cli_runner().invoke(
        args=["build-images", "--server", "tycho", "worker_synced_ubuntu2604_ssh"])
    assert result.exit_code == 0, result.output
    tasks = builds[0]["playbook"][0]["tasks"]
    assert [t["ansible.builtin.include_role"]["name"] for t in tasks] == ["worker_synced_ubuntu2604_ssh"]


def test_build_images_refuses_an_unknown_server_or_role(app, db, builds, make_server):
    make_server(hostname="tycho")
    runner = app.test_cli_runner()
    unknown_server = runner.invoke(args=["build-images", "--server", "nowhere"])
    assert unknown_server.exit_code != 0 and "No compute server 'nowhere'" in unknown_server.output
    unknown_role = runner.invoke(args=["build-images", "--server", "tycho", "worker_ollama"])
    assert unknown_role.exit_code != 0 and "worker_ollama" in unknown_role.output
    assert builds == []


def test_build_images_fails_when_ansible_does(app, db, monkeypatch, make_server):
    import app.image_builds as image_builds
    app.config["ANSIBLE_ROLES_PATH"] = str(ROLES_DIR)
    monkeypatch.setattr(image_builds.ansible_runner, "run", lambda **config: SimpleNamespace(status="failed", rc=2))
    make_server(hostname="tycho")
    result = app.test_cli_runner().invoke(args=["build-images", "--server", "tycho", "worker_local_ubuntu2604_ssh"])
    assert result.exit_code == 1
    assert "failed" in result.output


def test_without_a_registry_the_images_stay_on_the_server(app, db, builds, make_server):
    app.config["DOCKER_REGISTRY"] = ""
    make_server(hostname="tycho")
    result = app.test_cli_runner().invoke(args=["build-images", "--server", "tycho", "worker_local_ubuntu2604_ssh"])
    assert result.exit_code == 0, result.output
    assert "built on tycho only" in result.output
    assert builds[0]["playbook"][0]["tasks"][0]["vars"]["service_cfg"]["whap_registry"] == ""
