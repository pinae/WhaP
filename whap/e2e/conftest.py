"""Harness for WhaP's end-to-end tests.

The rig is described in rig.toml (see rig.example.toml). At the start of a
session the rig is put into a known state -- `flask e2e-reset` then
`flask e2e-seed` on the storage server -- and every test then works through
the browser as a person would, checking the storage server's filesystem where
a person would look there.
"""
import os
from contextlib import ExitStack
from collections.abc import Hashable
import secrets
import ssl
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from evidence import Recorder, container_evidence, slug
from pages import LoginPage
from rig import rig_for

HERE = Path(__file__).resolve().parent
RECORDER = pytest.StashKey[Recorder]()


def pytest_addoption(parser):
    parser.addoption("--rig", default=os.environ.get("WHAP_E2E_RIG", str(HERE / "rig.toml")),
                     help="Rig description (default: rig.toml next to this file, or $WHAP_E2E_RIG). "
                          "Write --rig=PATH: pytest takes a bare path for a test path.")
    parser.addoption("--force-reset", action="store_true",
                     help="Pass --force to e2e-reset: drop leftover container records of the test users "
                          "even though the containers may still exist on a compute server.")
    parser.addoption("--matrix", choices=("tiered", "full"), default="tiered",
                     help="Which roles the container matrix covers: 'tiered' (default) runs it on "
                          "[container] image only, 'full' on every worker role in roles/.")


# Phases run in this order, each building on the one before; other modules last.
PHASES = ["test_identity.py", "test_container_lifecycle.py", "test_container_matrix.py"]


@pytest.hookimpl(wrapper=True)
def pytest_collection_modifyitems(items):
    """Run phases in order, a matrix case's tests together, and each module's tests as written.

    pytest groups tests that share a module-scoped parameter, but across the
    whole session: it can move one of a case's tests past other modules,
    which would start that case's container twice. A wrapper, so this runs
    after that grouping and puts everything back.
    """
    yield
    cases = {}

    def position(item):
        phase = PHASES.index(item.path.name) if item.path.name in PHASES else len(PHASES)
        callspec = getattr(item, "callspec", None)
        case = callspec.params.get("case") if callspec else None
        # After every case. Not len(items): the list reads as empty while it is being sorted.
        case_index = cases.setdefault(case, len(cases)) if isinstance(case, Hashable) and case else float("inf")
        return phase, case_index, item.function.__code__.co_firstlineno

    items.sort(key=position)


# --- What a failure leaves behind ------------------------------------------------

def pytest_configure(config):
    config.stash[RECORDER] = Recorder(Path(config.getoption("--output")))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """On failure: keep the traces of the browser contexts the test used, and
    attach what is known about its container (see evidence.py)."""
    report = yield
    if report.failed:
        item.config.stash[RECORDER].test_failed(item)
        seen = set()
        for value in getattr(item, "funcargs", {}).values():
            # The container fixtures' values: Provisioned, Started.
            if hasattr(value, "card") and hasattr(value, "page") and id(value) not in seen:
                seen.add(id(value))
                out_dir = Path(item.config.getoption("--output")) / slug(item.nodeid)
                for title, text in container_evidence(value.page, value.card.id, rig_for(item.config), out_dir):
                    report.sections.append((f"whap: {title}", text))
    return report


@pytest.fixture(scope="session")
def recorder(pytestconfig):
    """Opens traced browser contexts: ``with recorder.context(browser, args, name=..., owner=...)``."""
    return pytestconfig.stash[RECORDER]


# --- The rig ------------------------------------------------------------------

@pytest.fixture(scope="session")
def rig(pytestconfig):
    return rig_for(pytestconfig)


def _whap_answers(rig, timeout=15):
    """Ask WhaP for a session as the login page does first; return why it failed, or None.

    When this request hangs, the page shows nothing but a spinner, and every
    test fails the same unhelpful way.
    """
    context = ssl.create_default_context()
    if rig.browser.get("ignore_https_errors"):
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    started = time.monotonic()
    try:
        with urllib.request.urlopen(f"{rig.url}/auth/session", timeout=timeout, context=context) as response:
            body = response.read(200).decode(errors="replace")
    except Exception as e:
        return (f"GET {rig.url}/auth/session failed after {time.monotonic() - started:.0f}s: {e}. "
                "The backend may be failing to start: see `docker logs whap-backend` on the storage server.")
    if '"isLoggedIn"' not in body:
        return f"GET {rig.url}/auth/session did not answer as WhaP's backend does: {body!r}"
    return None


@pytest.fixture(scope="session", autouse=True)
def known_state(rig, pytestconfig):
    """Clear what earlier runs left behind and (re)seed the infrastructure, once per session."""
    if (problem := _whap_answers(rig)) is not None:
        pytest.exit(problem, returncode=3)
    if not rig.seed_spec.exists():
        pytest.exit(f"Seed spec {rig.seed_spec} not found; copy seed.example.yml and fill it in.", returncode=4)
    spec = rig.seed_spec.read_text()
    reset_args = ["e2e-reset", *(["--force"] if pytestconfig.getoption("--force-reset") else []), "-"]
    for args in (reset_args, ["e2e-seed", "-"]):
        result = rig.flask(*args, input=spec, check=False)
        if result.returncode != 0:
            output = result.stdout + result.stderr
            if f"No such command '{args[0]}'" in output:
                pytest.exit(f"The backend on the storage server has no `flask {args[0]}`: it runs code from "
                            "before the e2e fixtures. Check out this branch where the server builds from "
                            "and redeploy; RUNNING-ON-THE-RIG.md step 1 says how to check.", returncode=3)
            hint = ("\n(From pytest, that is --force-reset.)"
                    if "--force" in output and "--force" not in args else "")
            pytest.exit(f"`flask {' '.join(args)}` failed on the storage server, so the rig is not in a "
                        f"known state:\n{output}{hint}", returncode=3)


@pytest.fixture(scope="session")
def run_id():
    """Distinguishes this session's names from any a crashed run left behind."""
    return secrets.token_hex(3)


# --- The browser --------------------------------------------------------------
# These override pytest-playwright's fixtures of the same name.

@pytest.fixture(scope="session")
def base_url(rig):
    return rig.url


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, rig):
    executable = rig.browser.get("executable")
    return {**browser_type_launch_args, **({"executable_path": executable} if executable else {})}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, rig):
    return {**browser_context_args, "ignore_https_errors": bool(rig.browser.get("ignore_https_errors"))}


@pytest.fixture
def login(browser, browser_context_args, rig, recorder, request):
    """login("alice") -> a UserPanel in a fresh browser context, signed in through the form.

    Each call gets its own context, so alice and bob can be signed in at once
    without sharing cookies. Each is traced, and the trace kept if the test fails.
    """
    with ExitStack() as contexts:
        def _login(who):
            user = rig.users[who]
            context = contexts.enter_context(recorder.context(
                browser, browser_context_args, name=f"{request.node.nodeid}-{who}", owner="login"))
            return LoginPage(context.new_page()).open().login(user.uid, user.password)

        yield _login


# --- Credentials --------------------------------------------------------------

@dataclass(frozen=True)
class KeyPair:
    private_key_path: Path
    public_key: str


@pytest.fixture(scope="session")
def ssh_keypair(tmp_path_factory, run_id):
    """A fresh ed25519 key pair; the private half never leaves this machine."""
    key = Ed25519PrivateKey.generate()
    path = tmp_path_factory.mktemp("ssh") / "id_ed25519"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    return KeyPair(path, f"{public.decode()} whap-e2e-{run_id}")
