"""Tests for the e2e test-rig commands (app.e2e_fixtures).

LDAP-owned rows are built by hand rather than with the conftest factories: the
app stores the *bare* uid on projects and containers ('e2e-alice') but the
prefixed one on memberships and SSH keys ('ldap:e2e-alice'), and reset has to
find both.
"""
import copy
import os
from pathlib import Path

import pytest
import yaml

from app.e2e_fixtures import E2EFixtureError, load_spec, reset, seed
from app.models import (ComputeServer, ContainerInstance, FileOperationJob, Group, GroupMembership,
                        Network, Project, ProjectShare, StaticAddress, UserSSHKey)
from app.services.permissions_service import get_user_permissions

EXAMPLE = Path(__file__).resolve().parents[2] / "e2e" / "seed.example.yml"

SPEC = {
    "servers": [{"hostname": "tycho", "ssh_port": 22, "gpu_count": 1}],
    "network": {"name": "e2e-lab", "base_ip": "192.168.50.0", "prefix_size": 24, "gateway": "192.168.50.1"},
    "addresses": [{"ip": "192.168.50.201", "mac": "02:57:68:61:50:01"},
                  {"ip": "192.168.50.202", "mac": "02:57:68:61:50:02"}],
    "group": {"name": "e2e", "members": ["ldap:e2e-alice", "ldap:e2e-bob"],
              "images": "*", "gpus": "all", "cpu_limit": None},
    "dataset": "e2e-dataset",
}


def spec(**overrides):
    data = copy.deepcopy(SPEC)
    for path, value in overrides.items():
        target = data
        *parents, leaf = path.split("__")
        for key in parents:
            target = target[key]
        target[leaf] = value
    return data


@pytest.fixture
def rig(app, db):
    """A test rig: fixtures enabled, and the dataset the whap role would create."""
    app.config["E2E_FIXTURES_ENABLED"] = True
    dataset = Path(app.config["DATASETS_BASE_PATH"]) / "e2e-dataset"
    dataset.mkdir(parents=True)
    (dataset / "e2e-marker.txt").write_text("whap-e2e-dataset\n")
    return app


def count(db, model):
    return db.session.scalar(db.select(db.func.count()).select_from(model))


# --- spec validation ----------------------------------------------------------

def test_shipped_example_spec_is_valid():
    load_spec(yaml.safe_load(EXAMPLE.read_text()))


@pytest.mark.parametrize("overrides, message", [
    ({"network__name": "lab-public"}, "ends in 'public'"),
    ({"network__name": "LAB-PUBLIC"}, "ends in 'public'"),
    ({"network__gateway": "10.0.0.1"}, "outside"),
    ({"network__base_ip": "192.168.50.7"}, "network"),          # not a network address
    ({"network__prefix_size": 31}, "between 8 and 30"),
    ({"addresses": [{"ip": "10.9.9.9", "mac": "02:00:00:00:00:01"}]}, "outside"),
    ({"addresses": [{"ip": "192.168.50.1", "mac": "02:00:00:00:00:01"}]}, "gateway"),
    ({"addresses": [{"ip": "192.168.50.9", "mac": "nope"}]}, "not a MAC"),
    ({"addresses": [{"ip": "192.168.50.9", "mac": "02:00:00:00:00:01"},
                    {"ip": "192.168.50.9", "mac": "02:00:00:00:00:02"}]}, "each ip"),
    ({"addresses": []}, "at least one address"),
    ({"servers": []}, "at least one compute server"),
    ({"group__members": ["e2e-alice"]}, "must be 'ldap:<uid>'"),
    ({"group__gpus": "first"}, "'all' or a list"),
    ({"group__cpu_limit": -1}, "positive number"),
])
def test_invalid_specs_are_rejected_with_a_reason(overrides, message):
    with pytest.raises(E2EFixtureError, match=message):
        load_spec(spec(**overrides))


def test_all_problems_are_reported_at_once():
    with pytest.raises(E2EFixtureError) as e:
        load_spec(spec(network__name="x-public", group__gpus="first"))
    assert "public" in str(e.value) and "'all' or a list" in str(e.value)


# --- the test-rig guard -------------------------------------------------------

@pytest.mark.parametrize("command", [seed, reset])
def test_refuses_to_run_outside_a_test_rig(app, db, command):
    app.config["E2E_FIXTURES_ENABLED"] = False
    with pytest.raises(E2EFixtureError, match="not a test rig"):
        command(load_spec(spec()))


# --- seed -----------------------------------------------------------------------

def test_seed_gives_the_test_users_what_they_need_to_start_a_container(rig, db):
    seed(load_spec(spec()))

    server = db.session.scalar(db.select(ComputeServer).filter_by(hostname="tycho"))
    assert server.gpu_count == 1
    addresses = db.session.scalars(db.select(StaticAddress)).all()
    assert {a.ip_address for a in addresses} == {"192.168.50.201", "192.168.50.202"}
    assert all(a.network.name == "e2e-lab" and a.available_servers == [server] for a in addresses)

    # What container creation actually checks:
    perms = get_user_permissions("ldap:e2e-alice")
    assert perms["accessible_server_ids"] == [server.id]
    assert perms["image_whitelist"] == ["*"]
    assert perms["gpu_access"] == {server.id: "all"}
    assert perms["cpu_limits"] == {server.id: None}
    assert get_user_permissions("ldap:e2e-bob")["accessible_server_ids"] == [server.id]


def test_seed_is_idempotent_and_updates_to_match(rig, db):
    seed(load_spec(spec()))
    seed(load_spec(spec(servers=[{"hostname": "TYCHO", "ssh_port": 2222, "gpu_count": 2}],
                        group__cpu_limit=4, group__gpus="0")))

    assert count(db, ComputeServer) == 1  # hostname matched case-insensitively
    assert count(db, Network) == 1 and count(db, StaticAddress) == 2
    assert count(db, Group) == 2          # Admins + e2e
    assert count(db, GroupMembership) == 2
    server = db.session.scalar(db.select(ComputeServer))
    assert (server.ssh_port, server.gpu_count) == (2222, 2)
    perms = get_user_permissions("ldap:e2e-alice")
    assert perms["gpu_access"] == {server.id: "0"}
    assert perms["cpu_limits"] == {server.id: 4}


def test_seed_does_not_take_over_another_networks_address(rig, db, make_network, make_static_address):
    office = make_network(name="office", base_ip="192.168.50.0", gateway="192.168.50.1")
    make_static_address(office, ip_address="192.168.50.201", mac_address="02:aa:aa:aa:aa:aa")

    with pytest.raises(E2EFixtureError, match="already belongs to network 'office'"):
        seed(load_spec(spec()))
    db.session.rollback()
    assert db.session.scalar(db.select(StaticAddress)).network.name == "office"


def test_seed_rejects_a_mac_used_by_another_address(rig, db, make_network, make_static_address):
    office = make_network(name="office", base_ip="10.0.0.0", gateway="10.0.0.1")
    make_static_address(office, ip_address="10.0.0.5", mac_address="02:57:68:61:50:01")
    with pytest.raises(E2EFixtureError, match="already used by address 10.0.0.5"):
        seed(load_spec(spec()))


def test_seed_checks_the_dataset_the_role_creates(rig, db):
    marker = Path(rig.config["DATASETS_BASE_PATH"]) / "e2e-dataset" / "e2e-marker.txt"
    marker.unlink()
    with pytest.raises(E2EFixtureError, match="read-only"):
        seed(load_spec(spec()))

    marker.write_text("something else\n")
    with pytest.raises(E2EFixtureError, match="expected 'whap-e2e-dataset'"):
        seed(load_spec(spec()))


# --- reset ----------------------------------------------------------------------

def _alice_and_bob_did_things(db, server):
    """What a test run leaves behind, stored the way the app stores it."""
    alice_project = Project(name="thesis", owner_uid="e2e-alice")
    bob_project = Project(name="shared", owner_uid="e2e-bob")
    db.session.add_all([alice_project, bob_project])
    db.session.flush()
    db.session.add(ProjectShare(project_id=bob_project.id, user_uid="ldap:e2e-alice", is_writable=True))
    db.session.add(UserSSHKey(user_uid="ldap:e2e-alice", name="laptop", public_key="ssh-ed25519 AAAA"))
    made_by_alice = Group(name="alice-team")
    db.session.add(made_by_alice)
    db.session.flush()
    db.session.add(GroupMembership(group_id=made_by_alice.id, user_uid="ldap:e2e-alice", is_group_admin=True))
    db.session.commit()
    return alice_project, bob_project


def test_reset_removes_test_data_and_keeps_infrastructure(rig, db):
    seed(load_spec(spec()))
    server = db.session.scalar(db.select(ComputeServer))
    _alice_and_bob_did_things(db, server)

    report = reset(load_spec(spec()))

    assert count(db, Project) == 0 and count(db, ProjectShare) == 0 and count(db, UserSSHKey) == 0
    assert db.session.scalar(db.select(Group).filter_by(name="alice-team")) is None
    # Infrastructure stays, including the seeded group's memberships.
    assert count(db, ComputeServer) == 1 and count(db, StaticAddress) == 2 and count(db, Network) == 1
    assert {m.user_uid for m in db.session.scalar(db.select(Group).filter_by(name="e2e")).members} \
        == {"ldap:e2e-alice", "ldap:e2e-bob"}
    # Project directories go through the worker, like a user's own delete.
    jobs = db.session.scalars(db.select(FileOperationJob)).all()
    paths = sorted(Path(j.payload.split('"path": "')[1].split('"')[0]).relative_to(rig.config["PROJECT_STORAGE_DIR"])
                   for j in jobs)
    assert [str(p) for p in paths] == ["e2e-alice/thesis", "e2e-bob/shared"]
    assert any("alice-team" in line for line in report)


def test_reset_can_keep_project_directories(rig, db):
    seed(load_spec(spec()))
    _alice_and_bob_did_things(db, db.session.scalar(db.select(ComputeServer)))
    reset(load_spec(spec()), keep_project_dirs=True)
    assert count(db, Project) == 0 and count(db, FileOperationJob) == 0


def test_reset_leaves_other_users_alone(rig, db, make_local_user, make_project, make_group, add_member):
    seed(load_spec(spec()))
    carol = make_local_user(username="carol")
    make_project(carol, name="real-work")
    mixed = make_group(name="mixed")
    add_member(mixed, carol)
    add_member(mixed, "ldap:e2e-alice")

    reset(load_spec(spec()))

    assert [p.name for p in db.session.scalars(db.select(Project))] == ["real-work"]
    assert {m.user_uid for m in db.session.scalar(db.select(Group).filter_by(name="mixed")).members} \
        == {f"local:{carol.id}"}  # alice's membership removed, the group kept


def _alice_container(db, status="RUNNING"):
    server = db.session.scalar(db.select(ComputeServer))
    project = Project(name="thesis", owner_uid="e2e-alice")
    db.session.add(project)
    db.session.flush()
    address = db.session.scalar(db.select(StaticAddress).filter_by(ip_address="192.168.50.201"))
    container = ContainerInstance(user_uid="e2e-alice", project_id=project.id, compute_server_id=server.id,
                                  image_name="worker_local_ubuntu2510_ssh", gpus="0", status=status,
                                  container_name="e2e-alice-thesis-1", static_address_id=address.id)
    db.session.add(container)
    db.session.commit()
    return container


def test_reset_stops_when_the_test_users_still_have_containers(rig, db):
    seed(load_spec(spec()))
    _alice_container(db, status="ERROR")  # may still exist half-started on tycho

    with pytest.raises(E2EFixtureError, match=r"1 container\(s\):\n  #\d+ e2e-alice-thesis-1 on tycho: ERROR"):
        reset(load_spec(spec()))
    db.session.rollback()
    assert count(db, ContainerInstance) == 1 and count(db, Project) == 1


def test_reset_force_deletes_container_records_and_frees_addresses(rig, db):
    seed(load_spec(spec()))
    _alice_container(db)

    report = reset(load_spec(spec()), force=True)

    assert count(db, ContainerInstance) == 0
    assert db.session.scalar(db.select(StaticAddress).filter_by(ip_address="192.168.50.201")).assigned_container is None
    assert any("remove it on tycho by hand" in line for line in report)


def test_reset_all_removes_the_seeded_infrastructure(rig, db):
    seed(load_spec(spec()))
    reset(load_spec(spec()), include_infrastructure=True)
    assert count(db, ComputeServer) == 0 and count(db, Network) == 0 and count(db, StaticAddress) == 0
    assert [g.name for g in db.session.scalars(db.select(Group))] == ["Admins"]


def test_reset_all_keeps_a_server_other_groups_still_use(rig, db, make_group):
    seed(load_spec(spec()))
    server = db.session.scalar(db.select(ComputeServer))
    make_group(name="real-users", servers=[server], gpu_rules={server.id: "0"})

    report = reset(load_spec(spec()), include_infrastructure=True)

    assert count(db, ComputeServer) == 1
    assert any("kept, still used by other groups' access, other groups' GPU rules" in line for line in report)


def test_reset_handles_local_test_users(rig, db, make_local_user, make_project):
    dave = make_local_user(username="dave")
    seed(load_spec(spec(group__members=[f"local:{dave.id}"])))
    make_project(dave, name="local-thesis")
    reset(load_spec(spec(group__members=[f"local:{dave.id}"])))
    assert count(db, Project) == 0


# --- CLI ----------------------------------------------------------------------

def test_cli_seeds_from_stdin_and_reports(rig, runner):
    result = runner.invoke(args=["e2e-seed", "-"], input=yaml.safe_dump(spec()))
    assert result.exit_code == 0, result.output
    assert "server tycho: created" in result.output
    assert "dataset e2e-dataset: present" in result.output


def test_cli_reports_a_bad_spec_without_a_traceback(rig, runner, tmp_path):
    bad = tmp_path / "seed.yml"
    bad.write_text(yaml.safe_dump(spec(network__name="lab-public")))
    result = runner.invoke(args=["e2e-seed", str(bad)])
    assert result.exit_code == 1
    assert "ends in 'public'" in result.output
    assert "Traceback" not in result.output


def test_cli_reset_flags(rig, runner, db):
    runner.invoke(args=["e2e-seed", "-"], input=yaml.safe_dump(spec()))
    result = runner.invoke(args=["e2e-reset", "--all", "-"], input=yaml.safe_dump(spec()))
    assert result.exit_code == 0, result.output
    assert "server tycho: deleted" in result.output
