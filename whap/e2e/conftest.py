"""Harness for WhaP's end-to-end tests.

The rig is described in rig.toml (see rig.example.toml). At the start of a
session the rig is put into a known state -- `flask e2e-reset` then
`flask e2e-seed` on the storage server -- and every test then works through
the browser as a person would, checking the storage server's filesystem where
a person would look there.
"""
import os
import secrets
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pages import LoginPage

HERE = Path(__file__).resolve().parent


def pytest_addoption(parser):
    parser.addoption("--rig", default=os.environ.get("WHAP_E2E_RIG", str(HERE / "rig.toml")),
                     help="Rig description (default: rig.toml next to this file, or $WHAP_E2E_RIG).")
    parser.addoption("--force-reset", action="store_true",
                     help="Pass --force to e2e-reset: drop leftover container records of the test users "
                          "even though the containers may still exist on a compute server.")


# --- The rig ------------------------------------------------------------------

@dataclass(frozen=True)
class User:
    uid: str
    password: str

    @property
    def prefixed(self):
        return f"ldap:{self.uid}"


@dataclass(frozen=True)
class ContainerSettings:
    image: str              # role the single-container tests use
    server: str | None      # hostname to pick; None when the user has only one server
    gpu: str                # GPU index to request
    gpu_name: str           # substring nvidia-smi must report, e.g. "2070"; "" to accept any
    start_timeout: int      # seconds; a fresh rig builds or pulls images on first use
    delete_timeout: int
    torch_index_url: str    # pip index for torch; "" for PyPI
    torch_install_timeout: int


class Rig:
    """What rig.toml describes, plus the commands to reach the storage server."""

    def __init__(self, path):
        path = Path(path)
        if not path.exists():
            pytest.exit(f"No rig description at {path}. Copy rig.example.toml to rig.toml and fill it in.",
                        returncode=4)
        data = tomllib.loads(path.read_text())
        try:
            self.url = data["whap"]["url"].rstrip("/")
            self.users = {key: User(u["uid"], u["password"]) for key, u in data["users"].items()}
            storage = data["storage"]
            self.shell = list(storage["shell"])
            self.backend_cli = list(storage["backend_cli"])
            self.seed_spec = (path.parent / storage["seed_spec"]).resolve()
            self.projects_dir = storage["projects_dir"].rstrip("/")
        except KeyError as e:
            pytest.exit(f"{path} is missing {e}; see rig.example.toml.", returncode=4)
        self.browser = data.get("browser", {})
        container, torch = data.get("container", {}), data.get("torch", {})
        self.container = ContainerSettings(
            image=container.get("image", "worker_local_ubuntu2510_ssh"),
            server=container.get("server"),
            gpu=str(container.get("gpu", "0")),
            gpu_name=container.get("gpu_name", ""),
            start_timeout=int(container.get("start_timeout", 1800)),
            delete_timeout=int(container.get("delete_timeout", 600)),
            torch_index_url=torch.get("index_url", ""),
            torch_install_timeout=int(torch.get("install_timeout", 1800)),
        )
        for key in ("alice", "bob"):
            if key not in self.users:
                pytest.exit(f"{path} needs a [users.{key}] section; see rig.example.toml.", returncode=4)

    def on_storage(self, *command, input=None, check=True):
        """Run a command on the storage server and return the completed process."""
        result = subprocess.run([*self.shell, *command], input=input, capture_output=True, text=True,
                                timeout=120)
        if check and result.returncode != 0:
            raise AssertionError(f"`{' '.join(command)}` on the storage server failed "
                                 f"({result.returncode}):\n{result.stdout}{result.stderr}")
        return result

    def flask(self, *args, input=None, check=True):
        """Run a backend `flask` command on the storage server."""
        return self.on_storage(*self.backend_cli, *args, input=input, check=check)


@pytest.fixture(scope="session")
def rig(pytestconfig):
    return Rig(pytestconfig.getoption("--rig"))


@pytest.fixture(scope="session", autouse=True)
def known_state(rig, pytestconfig):
    """Clear what earlier runs left behind and (re)seed the infrastructure, once per session."""
    if not rig.seed_spec.exists():
        pytest.exit(f"Seed spec {rig.seed_spec} not found; copy seed.example.yml and fill it in.", returncode=4)
    spec = rig.seed_spec.read_text()
    reset_args = ["e2e-reset", *(["--force"] if pytestconfig.getoption("--force-reset") else []), "-"]
    for args in (reset_args, ["e2e-seed", "-"]):
        result = rig.flask(*args, input=spec, check=False)
        if result.returncode != 0:
            hint = ("\n(From pytest, that is --force-reset.)"
                    if "--force" in result.stdout + result.stderr and "--force" not in args else "")
            pytest.exit(f"`flask {' '.join(args)}` failed on the storage server, so the rig is not in a "
                        f"known state:\n{result.stdout}{result.stderr}{hint}", returncode=3)


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
def login(browser, browser_context_args, rig):
    """login("alice") -> a UserPanel in a fresh browser context, signed in through the form.

    Each call gets its own context, so alice and bob can be signed in at once
    without sharing cookies.
    """
    contexts = []

    def _login(who):
        user = rig.users[who]
        context = browser.new_context(**browser_context_args)
        contexts.append(context)
        return LoginPage(context.new_page()).open().login(user.uid, user.password)

    yield _login
    for context in contexts:
        context.close()


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
