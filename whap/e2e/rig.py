"""The test rig as rig.toml describes it, and the roles the container tests cover."""
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

ROLES_DIR = Path(__file__).resolve().parents[2] / "roles"
# Roles the container tests leave out, and why (see README.md).
EXCLUDED_ROLES = {"worker_ollama": "serves an HTTP API, not SSH logins"}


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

    def project_dir(self, owner, project):
        """Where ``owner``'s (a key in [users]) project lives on the storage server."""
        return f"{self.projects_dir}/{self.users[owner].uid}/{project}"

    def owner_of(self, path, timeout=60):
        """Poll the storage server until ``path`` exists; return its uid:gid."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.on_storage("stat", "-c", "%u:%g", path, check=False)
            if result.returncode == 0:
                return result.stdout.strip()
            if time.monotonic() > deadline:
                raise AssertionError(f"{path} did not appear on the storage server within {timeout}s -- "
                                     f"is the worker running? stat said: {result.stderr.strip()}")
            time.sleep(1)


def rig_for(config):
    """The session's Rig; also usable at collection time, before fixtures exist."""
    if not hasattr(config, "_whap_rig"):
        config._whap_rig = Rig(config.getoption("--rig"))
    return config._whap_rig


def worker_roles():
    """Every worker role in the repository the container tests cover."""
    return sorted(d.name for d in ROLES_DIR.iterdir()
                  if d.is_dir() and d.name.startswith("worker_") and d.name not in EXCLUDED_ROLES)


def matrix_roles(config):
    """The roles --matrix selects."""
    if config.getoption("--matrix") == "full":
        return worker_roles()
    return [rig_for(config).container.image]
