"""Phase 1: signing in, and the things a user owns -- before any container runs.

Run first; everything later builds on a user who can sign in through LDAP,
has an SSH key, and owns a project whose directory the worker created.
"""
import re
import time

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

    # The worker creates it asynchronously, owned by alice's LDAP uid and gid.
    path = f"{rig.projects_dir}/{rig.users['alice'].uid}/{name}"
    assert wait_for_owner(rig, path) == ALICE_IDS


def test_shared_project_and_dataset_are_offered_as_volumes(login, rig, run_id):
    alice, bob = rig.users["alice"], rig.users["bob"]
    name = f"shared-{run_id}"
    bobs_projects = login("bob").projects()
    bobs_projects.create(name)
    bobs_projects.share(name, alice.prefixed)  # found through the LDAP user search

    offered = login("alice").create_container().mountable_volumes()

    assert f"Shared: {name} (ro)" in offered
    assert "Dataset: e2e-dataset (ro)" in offered


def wait_for_owner(rig, path, timeout=60):
    """Poll the storage server until ``path`` exists; return its uid:gid."""
    deadline = time.monotonic() + timeout
    while True:
        result = rig.on_storage("stat", "-c", "%u:%g", path, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        if time.monotonic() > deadline:
            raise AssertionError(f"{path} did not appear on the storage server within {timeout}s -- "
                                 f"is the worker running? stat said: {result.stderr.strip()}")
        time.sleep(1)
