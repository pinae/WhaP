"""Phases 3 and 4: how a user gets into a container, what it can mount, and every role.

Each case is one container, started through the form, then checked from
inside over SSH. In depth, on ``[container] image`` (Phase 3):

- ``key``: an SSH key and no password, with the e2e dataset and a project bob
  shared read-only. Both are readable; writing to either is refused.
- ``password``: a password and no key, with a project bob shared read-write.
  The key is refused; what alice writes lands in bob's project on the storage
  server, owned by her.

In breadth, on every other worker role in roles/ (Phase 4):

- ``both``: key and password, and the GPU. Both logins work, nvidia-smi sees
  the GPU, the tools users rely on work (USER_TOOLS), and the image does what
  it is for (PURPOSE).

``--matrix=full`` also runs the depth cases on every role. Cases run one after
another, each deleting its container before the next starts. One more test
needs no case: the form refusing a container with neither key nor password.
"""
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field

import paramiko
import pytest
from playwright.sync_api import expect

from containers import broken_user_tools, delete_container, tail, wait_until_settled
from pages import LoginPage
from remote import ContainerShell
from rig import matrix_roles, rig_for, worker_roles

ALICE_IDS = "70001:70000"  # fixed by the e2e LDAP directory
BOB_UID = "70002"
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


# What an image is for, where that is more than an Ubuntu with CUDA: checked
# over SSH, as the user will use it. role -> (what, command)
PURPOSE = {
    "worker_synced_nvidia_pytorch1906": (
        "its PyTorch computes on the GPU",
        "python -c 'import torch; assert torch.cuda.is_available(), \"no CUDA\"; "
        "print((torch.ones(2, device=\"cuda\") * 2).sum().item())'"),
    "worker_local_cuda-11-7_ubuntu2204_ssh": (
        "it has the CUDA 11.7 compiler",
        "/usr/local/cuda-11.7/bin/nvcc --version | grep 'release 11.7'"),
}


def cases_for(config):
    for role in matrix_roles(config):
        yield Case(role, "key", volumes=("dataset", "share-ro"))
        yield Case(role, "password", volumes=("share-rw",))
    # Phase 2 already takes [container] image through key, password and the GPU.
    primary = rig_for(config).container.image
    for role in worker_roles():
        if role != primary:
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

@contextmanager
def signed_in(recorder, browser, browser_context_args, rig, who, *, name, owner):
    """A UserPanel for ``who`` in a traced browser context of its own (see evidence.py)."""
    with recorder.context(browser, browser_context_args, name=name, owner=owner) as context:
        user = rig.users[who]
        yield LoginPage(context.new_page()).open().login(user.uid, user.password)


@pytest.fixture(scope="module")
def alice_key(browser, browser_context_args, rig, recorder, ssh_keypair, run_id):
    """The name of alice's SSH key, added once for every case."""
    name = f"e2e-matrix-{run_id}"
    with signed_in(recorder, browser, browser_context_args, rig, "alice", name="matrix-alice-key",
                   owner="alice_key") as panel:
        panel.ssh_keys().add(name, ssh_keypair.public_key)
    return name


@pytest.fixture(scope="module")
def bobs_shares(browser, browser_context_args, rig, recorder):
    """Bob's projects shared with alice, by kind: the volume label alice sees for each."""
    labels = {}
    with signed_in(recorder, browser, browser_context_args, rig, "bob", name="matrix-bobs-shares",
                   owner="bobs_shares") as panel:
        projects = panel.projects()
        for kind, name in BOB_SHARES.items():
            writable = kind == "share-rw"
            projects.create(name)
            projects.share(name, rig.users["alice"].prefixed, writable=writable)
            rig.owner_of(rig.project_dir("bob", name))  # the worker has made the directory
            labels[kind] = f"Shared: {name} ({'rw' if writable else 'ro'})"
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
def started(case, browser, browser_context_args, rig, recorder, alice_key, bobs_shares):
    """Start the case's container through the form and wait for it to settle. Asserts nothing."""
    with signed_in(recorder, browser, browser_context_args, rig, "alice", name=f"matrix-{case.id}",
                   owner="started") as panel:
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


@applies_to(lambda case: case.gpu)
def test_the_tools_users_need_work(running, rig, ssh_keypair):
    """nvtop, tmux, and a virtualenv with pip."""
    with shell(running, rig, ssh_keypair) as sh:
        broken = broken_user_tools(sh, running.case.role)
    assert not broken, broken


@applies_to(lambda case: case.gpu and case.role in PURPOSE)
def test_the_image_does_what_it_is_for(running, rig, ssh_keypair):
    what, command = PURPOSE[running.case.role]
    with shell(running, rig, ssh_keypair) as sh:
        result = sh.run(command)
    assert result.exit_status == 0, f"expected that {what}:\n{result}"


# --- Volumes ---------------------------------------------------------------------

def assert_is_bobs_project(sh, path, rig):
    """Docker mounts an empty directory it makes up (root's, 0755) when the
    source path is missing on the compute server. Make sure this is the real one."""
    owner = sh.run(f"stat -c %u {path}").stdout.strip()
    assert owner == BOB_UID, (
        f"{path} belongs to uid {owner}, not bob ({BOB_UID}): it is a placeholder Docker made because "
        f"the compute server has no such project under {rig.compute_data_dir} -- is the storage server's "
        f"projects_dir mounted there? See test_the_compute_server_sees_the_projects_and_datasets.")


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
        assert marker.exit_status == 0 and marker.stdout.strip() == content, (
            f"{marker}\nIf the dataset directory is empty, the compute server has no "
            f"{rig.compute_data_dir}/DATASETS: see test_the_compute_server_sees_the_projects_and_datasets.")
        assert_read_only(sh, path)


@applies_to(lambda case: "share-ro" in case.volumes)
def test_a_read_only_share_is_readable_but_not_writable(running, rig, ssh_keypair):
    path = running.mounts["share-ro"]
    with shell(running, rig, ssh_keypair) as sh:
        assert_is_bobs_project(sh, path, rig)
        listing = sh.run(f"ls -A {path}")
        assert listing.exit_status == 0, str(listing)
        assert_read_only(sh, path)


@applies_to(lambda case: "share-rw" in case.volumes)
def test_writes_to_a_writable_share_land_in_the_owners_project(running, rig, ssh_keypair, run_id):
    path = running.mounts["share-rw"]
    name, content = f"from-alice-{running.case.id}.txt", f"written by alice in run {run_id}"
    with shell(running, rig, ssh_keypair) as sh:
        assert_is_bobs_project(sh, path, rig)
        write = sh.run(f"printf %s '{content}' > {path}/{name}")
        context = sh.run(f"id; ls -ldn {path}").stdout
    assert write.exit_status == 0, (f"alice could not write to bob's project, shared with her read-write:\n"
                                    f"{write}\n--- in the container ---\n{context}")

    on_storage = f"{rig.project_dir('bob', BOB_SHARES['share-rw'])}/{name}"
    assert rig.owner_of(on_storage, timeout=10) == ALICE_IDS
    assert rig.on_storage("cat", on_storage).stdout == content


@applies_to(lambda case: case.gpu and case.role.startswith("worker_synced_"))
def test_a_synced_home_reaches_the_storage_server(running, rig, ssh_keypair, run_id):
    """What makes a synced container synced: its home directory is the project
    on the storage server, so nothing is lost with the compute server."""
    name, content = f".e2e-synced-{run_id}", f"synced from {running.case.id}"
    with shell(running, rig, ssh_keypair) as sh:
        write = sh.run(f"printf %s '{content}' > ~/{name}")
    assert write.exit_status == 0, str(write)
    on_storage = f"{rig.project_dir('alice', running.case.project)}/{name}"
    assert rig.owner_of(on_storage, timeout=10) == ALICE_IDS, f"{on_storage} not found on the storage server"
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
