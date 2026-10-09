"""Phase 1: signing in, and the things a user owns -- before any container runs.

Run first; everything later builds on a user who can sign in through LDAP,
has an SSH key, and owns a project whose directory the worker created.
"""
import re

import pytest

from playwright.sync_api import expect

from pages import LoginPage

# Fixed by the e2e LDAP directory (whap/e2e/ldap/entrypoint.sh).
ALICE_IDS = "70001:70000"


def test_ldap_user_signs_in_and_out(page, rig):
    alice = rig.users["alice"]
    panel = LoginPage(page).open().login(alice.uid, alice.password)

    # An LDAP session, not a local account that happens to share the name.
    session = page.request.get("/auth/session").json()
    assert session["user"]["id"] == alice.prefixed
    assert session["user"]["user_type"] == "ldap"

    panel.logout()
    assert page.request.get("/auth/session").json()["isLoggedIn"] is False


def test_wrong_password_is_refused(page, rig):
    alice = rig.users["alice"]
    form = LoginPage(page).open()
    form.attempt(alice.uid, "not-" + alice.password)

    expect(form.error).to_have_text("Invalid credentials")
    expect(page).to_have_url(re.compile(r"/login$"))
    assert page.request.get("/auth/session").json()["isLoggedIn"] is False


def test_user_adds_an_ssh_key(login, ssh_keypair, run_id):
    panel = login("alice")
    name = f"laptop-{run_id}"
    panel.ssh_keys().add(name, ssh_keypair.public_key)

    # Stored, not just shown: it survives a reload, byte for byte.
    panel.page.reload()
    assert panel.ssh_keys().shown_public_key(name) == ssh_keypair.public_key


def test_user_creates_a_project_and_the_worker_makes_its_directory(login, rig, run_id):
    name = f"thesis-{run_id}"
    login("alice").projects().create(name)

    # The worker creates it asynchronously, owned by alice's LDAP uid and gid,
    # and group-writable so that sharing it read-write works.
    path = rig.project_dir("alice", name)
    assert rig.owner_of(path) == ALICE_IDS
    assert rig.on_storage("stat", "-c", "%a", path).stdout.strip() == "2775"


def test_shared_project_and_dataset_are_offered_as_volumes(login, rig, run_id):
    alice = rig.users["alice"]
    name = f"shared-{run_id}"
    bobs_projects = login("bob").projects()
    bobs_projects.create(name)
    bobs_projects.share(name, alice.prefixed)  # found through the LDAP user search

    offered = login("alice").create_container().mountable_volumes()

    assert f"Shared: {name} (ro)" in offered
    assert "Dataset: e2e-dataset (ro)" in offered


def test_the_compute_server_sees_the_projects_and_datasets(login, rig, run_id):
    """Containers bind-mount projects and datasets by the paths WhaP knows them
    by. If the compute server's /data is not the storage server's projects_dir,
    Docker mounts an empty directory it makes up instead, and a user's shared
    project or dataset is silently empty."""
    if not rig.compute_shell:
        pytest.skip("set [compute] shell in rig.toml to check the compute server")
    name = f"nfs-{run_id}"
    login("alice").projects().create(name)
    rig.owner_of(rig.project_dir("alice", name))  # made on the storage server

    project = f"{rig.compute_data_dir}/{rig.users['alice'].uid}/{name}"
    seen = rig.on_compute("stat", "-c", "%u:%g", project)
    marker = rig.on_compute("cat", f"{rig.compute_data_dir}/DATASETS/e2e-dataset/e2e-marker.txt")
    mounts = rig.on_compute("findmnt", "-T", rig.compute_data_dir).stdout
    assert seen.stdout.strip() == ALICE_IDS, (
        f"the compute server has no {project}, which the storage server just made: its "
        f"{rig.compute_data_dir} is not the storage server's projects_dir.\n{seen.stderr}\n{mounts}")
    assert marker.stdout.strip() == "whap-e2e-dataset", f"no e2e dataset on the compute server\n{marker.stderr}"
