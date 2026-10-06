"""Phase 3: how a user gets into a container, and what it can mount.

Each case is one container, started through the form with one way of logging
in and some extra volumes, then checked from inside over SSH:

- ``key``: an SSH key and no password, with the e2e dataset and a project bob
  shared read-only. Both are readable; writing to either is refused.
- ``password``: a password and no key, with a project bob shared read-write.
  The key is refused; what alice writes lands in bob's project on the storage
  server, owned by her.
- ``both`` (--matrix=full only): key and password, and the GPU.

``--matrix=tiered`` (the default) runs the cases on ``[container] image``;
``--matrix=full`` on every worker role in roles/. Cases run one after another,
each deleting its container before the next starts. Two more tests need no
case: the form refusing a container with neither key nor password, and a
password-only container in a project that once had a key.
"""
import secrets
from dataclasses import dataclass, field

import paramiko
import pytest
from playwright.sync_api import expect

from rig import matrix_roles
from containers import delete_container, tail, wait_until_settled
from pages import LoginPage
from remote import ContainerShell

ALICE_IDS = "70001:70000"  # fixed by the e2e LDAP directory
DATASET = "Dataset: e2e-dataset (ro)"
DATASET_MARKER = ("e2e-marker.txt", "whap-e2e-dataset")  # written by the whap role
BOB_SHARES = {"share-ro": "e2e-bob-ro", "share-rw": "e2e-bob-rw"}


# --- The cases -------------------------------------------------------------------

@dataclass(frozen=True)
class Case:
    role: str
    auth: str                 # "key", "password" or "both"
    volumes: tuple = ()       # "dataset", "share-ro", "share-rw"
    gpu: bool = False

    @property
    def key(self):
        return self.auth in ("key", "both")

    @property
    def password(self):
        return self.auth in ("password", "both")

    @property
    def id(self):
        short = self.role.removeprefix("worker_").removesuffix("_ssh").replace("_", "-")
        return f"{short}-{self.auth}"

    @property
    def project(self):
        # Fixed, so local roles reuse one home directory on the compute server
        # rather than leaving a new one behind every run.
        return f"e2e-m-{self.id}"


def cases_for(config):
    full = config.getoption("--matrix") == "full"
    for role in matrix_roles(config):
        yield Case(role, "key", volumes=("dataset", "share-ro"))
        yield Case(role, "password", volumes=("share-rw",))
        if full:
            yield Case(role, "both", gpu=True)


def applies_to(predicate):
    """Run the test only for the cases ``predicate`` accepts."""
    def mark(test):
        test.applies_to = predicate
        return test
    return mark


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        wanted = getattr(metafunc.function, "applies_to", lambda case: True)
        cases = [case for case in cases_for(metafunc.config) if wanted(case)]
        # Module scope: one container per case, shared by that case's tests.
        metafunc.parametrize("case", cases, ids=[case.id for case in cases], scope="module")


# --- What every case needs -------------------------------------------------------

def signed_in(browser, browser_context_args, rig, who):
    context = browser.new_context(**browser_context_args)
    user = rig.users[who]
    return context, LoginPage(context.new_page()).open().login(user.uid, user.password)


@pytest.fixture(scope="module")
def alice_key(browser, browser_context_args, rig, ssh_keypair, run_id):
    """The name of alice's SSH key, added once for every case."""
    context, panel = signed_in(browser, browser_context_args, rig, "alice")
    name = f"e2e-matrix-{run_id}"
    panel.ssh_keys().add(name, ssh_keypair.public_key)
    context.close()
    return name


@pytest.fixture(scope="module")
def bobs_shares(browser, browser_context_args, rig):
    """Bob's projects shared with alice, by kind: the volume label alice sees for each."""
    context, panel = signed_in(browser, browser_context_args, rig, "bob")
    projects = panel.projects()
    labels = {}
    for kind, name in BOB_SHARES.items():
        writable = kind == "share-rw"
        projects.create(name)
        projects.share(name, rig.users["alice"].prefixed, writable=writable)
        rig.owner_of(rig.project_dir("bob", name))  # the worker has made the directory
        labels[kind] = f"Shared: {name} ({'rw' if writable else 'ro'})"
    context.close()
    return labels


@dataclass
class Started:
    case: Case
    page: object
    card: object
    password: str | None
    mounts: dict = field(default_factory=dict)  # volume kind -> path in the container
    final_status: str = ""
    log_text: str = ""


@pytest.fixture(scope="module")
def started(case, browser, browser_context_args, rig, alice_key, bobs_shares):
    """Start the case's container through the form and wait for it to settle. Asserts nothing."""
    context, panel = signed_in(browser, browser_context_args, rig, "alice")
    card = None
    try:
        panel.projects().create(case.project)
        labels = {kind: DATASET if kind == "dataset" else bobs_shares[kind] for kind in case.volumes}
        password = secrets.token_urlsafe(12) if case.password else None

        form = panel.create_container()
        card = form.start(project=case.project, image=case.role, ssh_key=alice_key if case.key else None,
                          password=password, server=rig.container.server,
                          gpus=[rig.container.gpu] if case.gpu else (), volumes=labels.values())
        run = Started(case, panel.page, card, password,
                      mounts={kind: form.mount_paths[label] for kind, label in labels.items()})
        run.final_status = wait_until_settled(card, rig.container.start_timeout)
        run.log_text = card.log_text()
        yield run
    finally:
        if card:
            delete_container(panel.page, card.id, rig.container.delete_timeout)
        context.close()


@pytest.fixture(scope="module")
def running(started):
    if started.final_status != "RUNNING":
        pytest.skip(f"the container is {started.final_status}, not RUNNING (see test_container_reaches_running)")
    return started


def shell(run, rig, ssh_keypair, *, by=None):
    """Log in as alice, by key or password; by default with whichever the case has (the key first)."""
    by = by or ("key" if run.case.key else "password")
    credentials = {"key_path": ssh_keypair.private_key_path} if by == "key" else {"password": run.password}
    return ContainerShell(run.card.ip(), rig.users["alice"].uid, **credentials)


# --- Logging in ------------------------------------------------------------------

def test_container_reaches_running(started, rig):
    assert started.final_status == "RUNNING", (
        f"the container ended {started.final_status!r} (start_timeout {rig.container.start_timeout}s). "
        f"Last lines of its log:\n{tail(started.log_text)}")


@applies_to(lambda case: case.key)
def test_login_with_the_key(running, rig, ssh_keypair):
    with shell(running, rig, ssh_keypair, by="key") as sh:
        result = sh.run("id -un; id -u; id -g")
    assert result.stdout.split() == [rig.users["alice"].uid, *ALICE_IDS.split(":")], str(result)


@applies_to(lambda case: case.password)
def test_login_with_the_password(running, rig, ssh_keypair):
    with shell(running, rig, ssh_keypair, by="password") as sh:
        result = sh.run("id -un")
    assert result.stdout.strip() == rig.users["alice"].uid, str(result)


@applies_to(lambda case: not case.key)
def test_without_a_key_the_key_is_refused(running, rig, ssh_keypair):
    with pytest.raises(paramiko.AuthenticationException):
        shell(running, rig, ssh_keypair, by="key").close()


@applies_to(lambda case: case.gpu)
def test_the_requested_gpu_is_visible(running, rig, ssh_keypair):
    with shell(running, rig, ssh_keypair) as sh:
        smi = sh.run("nvidia-smi --query-gpu=name --format=csv,noheader")
    gpus = [line.strip() for line in smi.stdout.splitlines() if line.strip()]
    assert smi.exit_status == 0 and len(gpus) == 1, str(smi)
    assert rig.container.gpu_name in gpus[0], f"expected a GPU named like {rig.container.gpu_name!r}: {gpus}"


# --- Volumes ---------------------------------------------------------------------

def assert_read_only(sh, path):
    """Writing under ``path`` fails because the mount is read-only, not for some other reason."""
    probe = sh.run(f"touch {path}/.e2e-write-probe")
    assert probe.exit_status != 0, f"{path} should be read-only, but a file could be created there"
    assert "Read-only file system" in probe.stderr, f"writing to {path} failed for another reason:\n{probe}"


@applies_to(lambda case: "dataset" in case.volumes)
def test_the_dataset_is_mounted_read_only(running, rig, ssh_keypair):
    path = running.mounts["dataset"]
    name, content = DATASET_MARKER
    with shell(running, rig, ssh_keypair) as sh:
        marker = sh.run(f"cat {path}/{name}")
        assert marker.exit_status == 0 and marker.stdout.strip() == content, str(marker)
        assert_read_only(sh, path)


@applies_to(lambda case: "share-ro" in case.volumes)
def test_a_read_only_share_is_readable_but_not_writable(running, rig, ssh_keypair):
    path = running.mounts["share-ro"]
    with shell(running, rig, ssh_keypair) as sh:
        listing = sh.run(f"ls -A {path}")
        assert listing.exit_status == 0, str(listing)
        assert_read_only(sh, path)


@applies_to(lambda case: "share-rw" in case.volumes)
def test_writes_to_a_writable_share_land_in_the_owners_project(running, rig, ssh_keypair, run_id):
    path = running.mounts["share-rw"]
    name, content = f"from-alice-{running.case.id}.txt", f"written by alice in run {run_id}"
    with shell(running, rig, ssh_keypair) as sh:
        write = sh.run(f"printf %s '{content}' > {path}/{name}")
        mode = sh.run(f"stat -c %a {path}").stdout.strip()
        context = sh.run(f"id; ls -ldn {path}").stdout
    if write.exit_status != 0 and "Permission denied" in write.stderr and not int(mode[-2]) & 2:
        pytest.xfail(f"Known issue: project directories are created {mode}, without group write, so a "
                     f"read-write share is read-only to everyone but the owner. Remove this branch once "
                     f"shared project directories are group-writable.\n{context}")
    assert write.exit_status == 0, (f"alice could not write to bob's project, shared with her read-write:\n"
                                    f"{write}\n--- in the container ---\n{context}")

    on_storage = f"{rig.project_dir('bob', BOB_SHARES['share-rw'])}/{name}"
    assert rig.owner_of(on_storage, timeout=10) == ALICE_IDS
    assert rig.on_storage("cat", on_storage).stdout == content


# --- No case ---------------------------------------------------------------------

def test_the_form_refuses_a_container_without_key_or_password(login, rig):
    project = "e2e-m-neither"
    panel = login("alice")
    panel.projects().create(project)
    form = panel.create_container()

    form.fill(project=project, image=rig.container.image, server=rig.container.server).submit()

    assert "A password or an SSH key is required" in form.error()
    expect(panel.page.get_by_test_id("tab-create")).to_have_attribute("aria-selected", "true")
    created = [c for c in panel.page.request.get("/api/containers").json() if c["project"] == project]
    assert created == [], f"a container was created anyway: {created}"


def test_a_key_from_an_earlier_container_does_not_open_a_password_only_one(login, rig, ssh_keypair, run_id):
    """The key is written to authorized_keys in the project's home directory,
    which outlives the container. A later container in the same project
    without a key skips that step, so the old file -- and the old key -- stay.
    """
    project = "e2e-m-rekey"
    panel = login("alice")
    panel.ssh_keys().add(f"e2e-rekey-{run_id}", ssh_keypair.public_key)
    panel.projects().create(project)
    password = secrets.token_urlsafe(12)
    image, timeout = rig.container.image, rig.container.start_timeout

    keyed = panel.create_container().start(project=project, image=image, ssh_key=f"e2e-rekey-{run_id}",
                                           server=rig.container.server)
    try:
        assert wait_until_settled(keyed, timeout) == "RUNNING", tail(keyed.log_text())
    finally:
        delete_container(panel.page, keyed.id, rig.container.delete_timeout)

    later = panel.create_container().start(project=project, image=image, password=password,
                                           server=rig.container.server)
    try:
        assert wait_until_settled(later, timeout) == "RUNNING", tail(later.log_text())
        with ContainerShell(later.ip(), rig.users["alice"].uid, password=password) as sh:
            assert sh.run("true").exit_status == 0  # the container is up and takes its password
        try:
            ContainerShell(later.ip(), rig.users["alice"].uid, key_path=ssh_keypair.private_key_path).close()
        except paramiko.AuthenticationException:
            return  # refused, as it should be
        pytest.xfail("Known issue: the first container's key still opens the second. Remove this "
                     "branch once authorized_keys follows the container's choice.")
    finally:
        delete_container(panel.page, later.id, rig.container.delete_timeout)
