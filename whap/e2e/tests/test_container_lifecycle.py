"""Phase 2: one container, from the form to a PyTorch tensor on the GPU, and gone again.

The module creates a single container through the form, watching its Ansible
log arrive and reloading the page once mid-job. Each test then checks one
thing about it, so a failure says what broke. If the container never reaches
RUNNING, that test fails with the log attached and the ones that need a
running container are skipped rather than failing on top of it.

The project name is fixed: for local roles the project's home directory lives
on the compute server, which reset never touches, so the virtualenv the torch
test installs into is reused by every later run.
"""
import json
import re
import secrets
import time
from dataclasses import dataclass, field

import pytest
from playwright.sync_api import expect

from containers import broken_user_tools, delete_container, tail
from pages import LoginPage
from pages.user_panel import ContainerCard
from remote import ContainerShell

PROJECT = "e2e-gpu"
ALICE_IDS = ["70001", "70000"]  # fixed by the e2e LDAP directory


# --- What the browser received ---------------------------------------------------

@dataclass
class Frame:
    at: float     # time.monotonic() when the browser received it
    event: str
    data: dict


class SocketRecorder:
    """Records every Socket.IO event the page receives, across reloads."""

    def __init__(self, page):
        self.frames = []
        page.on("websocket", lambda ws: ws.on("framereceived", self._received))

    def _received(self, payload):
        # Socket.IO event packets are "42", an optional ack id, then a JSON array.
        if isinstance(payload, bytes) or not payload.startswith("42"):
            return
        try:
            event, data = json.loads(payload[payload.index("["):])[:2]
        except (ValueError, TypeError):
            return
        self.frames.append(Frame(time.monotonic(), event, data if isinstance(data, dict) else {}))

    def events(self, name, container_id, before=None):
        return [f for f in self.frames if f.event == name and str(f.data.get("container_id")) == container_id
                and (before is None or f.at < before)]


@dataclass
class Provisioned:
    page: object
    card: ContainerCard
    sockets: SocketRecorder
    password: str
    line_counts: list = field(default_factory=list)  # distinct live-line counts, in the order seen
    reloaded_at: float | None = None
    replayed: str | None = None                      # the log pane right after the reload
    final_status: str = ""
    log_text: str = ""

    def api(self, path):
        return self.page.request.get(path)


@pytest.fixture(scope="module")
def provisioned(browser, browser_context_args, rig, recorder, ssh_keypair, run_id):
    """Create the container through the form and record how it came up. Asserts nothing."""
    with recorder.context(browser, browser_context_args, name="lifecycle", owner="provisioned") as context:
        page = context.new_page()
        sockets = SocketRecorder(page)
        alice = rig.users["alice"]
        panel = LoginPage(page).open().login(alice.uid, alice.password)
        key_name = f"e2e-{run_id}"
        panel.ssh_keys().add(key_name, ssh_keypair.public_key)
        panel.projects().create(PROJECT)

        password = secrets.token_urlsafe(12)
        card = panel.create_container().start(
            project=PROJECT, image=rig.container.image, ssh_key=key_name, password=password,
            server=rig.container.server, gpus=[rig.container.gpu])
        run = Provisioned(page, card, sockets, password)

        deadline = time.monotonic() + rig.container.start_timeout
        while run.card.status in ContainerCard.BUSY and time.monotonic() < deadline:
            if run.reloaded_at is None:
                count = run.card.live_lines()
                if not run.line_counts or count != run.line_counts[-1]:
                    run.line_counts.append(count)
                if len(run.line_counts) >= 4:  # the log has visibly grown three times
                    _reload_mid_job(run)
            page.wait_for_timeout(250)

        run.final_status = run.card.status
        run.log_text = run.card.log_text()
        yield run

        delete_container(page, run.card.id, rig.container.delete_timeout)


def _reload_mid_job(run):
    """Reload the page as an impatient person would, and capture what the log shows."""
    run.reloaded_at = time.monotonic()
    run.page.reload()
    run.card = ContainerCard(run.page, run.card.id)
    expect(run.card.locator).to_be_visible()
    until = time.monotonic() + 20
    while time.monotonic() < until and run.card.status in ContainerCard.BUSY:
        if run.card.live_lines() > 0:
            run.replayed = run.card.log.inner_text()
            return
        run.page.wait_for_timeout(250)


@pytest.fixture(scope="module")
def running(provisioned):
    if provisioned.final_status != "RUNNING":
        pytest.skip(f"the container is {provisioned.final_status}, not RUNNING (see test_container_reaches_running)")
    return provisioned


def shell(run, rig, **credentials):
    return ContainerShell(run.card.ip(), rig.users["alice"].uid, **credentials)


# --- The log ---------------------------------------------------------------------

def test_ansible_log_streams_into_the_browser(provisioned):
    run = provisioned
    live = run.sockets.events("ansible_log", run.card.id, before=run.reloaded_at)
    assert len(live) >= 5, f"only {len(live)} ansible_log frames reached the browser before the reload"
    assert live[-1].at - live[0].at >= 1.0, "every line arrived at once: dumped at the end, not streamed"
    assert len(run.line_counts) >= 3, f"the log pane did not visibly grow; line counts seen: {run.line_counts}"
    assert re.search(r"(PLAY|TASK) \[", run.log_text), "no Ansible output in the log pane"

    completed = run.sockets.events("ansible_job_completed", run.card.id)
    assert completed, "no ansible_job_completed frame: the browser was never told the job ended"
    last_line = run.sockets.events("ansible_log", run.card.id)[-1]
    assert completed[-1].at >= last_line.at, "the job was reported complete before its last log line arrived"


def test_reloading_mid_job_replays_the_log_so_far(provisioned):
    if provisioned.reloaded_at is None:
        pytest.skip("the job finished before its log had visibly grown, so there was no moment to reload")
    assert provisioned.replayed, "after reloading, no log line arrived while the job was still running"
    assert "Starting Ansible job for action: create" in provisioned.replayed


def test_the_log_does_not_reveal_the_container_password(provisioned):
    """The password is redacted before the log is stored, streamed or replayed."""
    run = provisioned
    streamed = "".join(json.dumps(f.data) for f in run.sockets.frames)
    stored = run.api(f"/api/containers/{run.card.id}").json()["ansible_log"] or ""
    for where, text in {"stored log": stored, "log pane": run.log_text, "Socket.IO frames": streamed}.items():
        assert run.password not in text, f"the container password appears in the {where}"


# --- The container ---------------------------------------------------------------

def test_container_reaches_running(provisioned, rig):
    assert provisioned.final_status == "RUNNING", (
        f"the container ended {provisioned.final_status!r} "
        f"(start_timeout {rig.container.start_timeout}s). Last lines of its log:\n{tail(provisioned.log_text)}")


def test_card_shows_how_to_connect(running, rig):
    assert running.card.ssh_command() == f"ssh {rig.users['alice'].uid}@{running.card.ip()}"


def test_login_with_the_ssh_key(running, rig, ssh_keypair):
    with shell(running, rig, key_path=ssh_keypair.private_key_path) as sh:
        result = sh.run("id -un; id -u; id -g")
    assert result.stdout.split() == [rig.users["alice"].uid, *ALICE_IDS], str(result)


def test_login_with_the_password(running, rig):
    with shell(running, rig, password=running.password) as sh:
        result = sh.run("id -un")
    assert result.stdout.strip() == rig.users["alice"].uid, str(result)


def test_the_requested_gpu_and_only_it_is_visible(running, rig, ssh_keypair):
    with shell(running, rig, key_path=ssh_keypair.private_key_path) as sh:
        smi = sh.run("nvidia-smi --query-gpu=name --format=csv,noheader")
    assert smi.exit_status == 0, str(smi)
    gpus = [line.strip() for line in smi.stdout.splitlines() if line.strip()]
    assert len(gpus) == 1, f"expected exactly the requested GPU, nvidia-smi lists {gpus}"
    assert rig.container.gpu_name in gpus[0], f"expected a GPU named like {rig.container.gpu_name!r}, got {gpus[0]!r}"


def test_the_tools_users_need_work(running, rig, ssh_keypair):
    """nvtop, tmux, and a virtualenv with pip."""
    with shell(running, rig, key_path=ssh_keypair.private_key_path) as sh:
        broken = broken_user_tools(sh, rig.container.image)
    assert not broken, broken


TORCH_CHECK = """
import torch
assert torch.cuda.is_available(), "torch sees no CUDA device"
x = torch.randn(4096, 4096, device="cuda")
checksum = (x @ x).sum().item()
torch.cuda.synchronize()
print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0), sep="|")
"""


def test_pytorch_computes_on_the_gpu(running, rig, ssh_keypair):
    """Installs torch into a virtualenv in the project's home on first use; later runs reuse it."""
    index = f"--index-url {rig.container.torch_index_url} " if rig.container.torch_index_url else ""
    script = ("set -e\n"
              "test -x ~/.e2e-venv/bin/python || python3 -m venv ~/.e2e-venv\n"
              "~/.e2e-venv/bin/python -c 'import torch' 2>/dev/null || "
              f"~/.e2e-venv/bin/pip install --quiet --cache-dir ~/.e2e-pip-cache {index}torch\n"
              f"~/.e2e-venv/bin/python - <<'PY'{TORCH_CHECK}PY\n")
    with shell(running, rig, key_path=ssh_keypair.private_key_path) as sh:
        result = sh.run(script, timeout=rig.container.torch_install_timeout)
    assert result.exit_status == 0, str(result)
    version, cuda, device = result.stdout.strip().splitlines()[-1].split("|")
    assert rig.container.gpu_name in device, f"torch {version} (CUDA {cuda}) ran on {device!r}"


# --- And gone again --------------------------------------------------------------
# Last in the file: pytest runs tests in order, and this one removes the container.

def test_deleting_the_container_releases_its_address(provisioned, rig):
    run = provisioned
    address = run.api(f"/api/containers/{run.card.id}").json()["ip_address"]
    run.card.delete()
    expect(run.card.locator).to_be_hidden(timeout=rig.container.delete_timeout * 1000)

    assert run.api(f"/api/containers/{run.card.id}").status == 404
    if address:  # a container that failed to start has already given its address back
        pool = {a["ip_address"]: a for a in run.api("/api/my-static_addresses").json()}
        assert pool[address]["assigned_container_id"] is None, f"{address} is still assigned"
