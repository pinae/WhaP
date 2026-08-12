"""Shared pytest fixtures and factories for the WhaP backend test suite.

Design notes:
* File-backed SQLite under a tmp dir (not ``:memory:``) so the schema is shared
  across the threads the Socket.IO ``threading`` test client may use.
* The Redis Socket.IO backplane is disabled (SOCKETIO_MESSAGE_QUEUE="") before
  the app package is imported, so the suite needs no external services.
* The schema is created with ``db.create_all()`` (not migrations), so seed data
  a migration would create — the ``Admins`` group with id 0 — is created here.
* Identity always flows through the factories, so the prefixed ("local:<id>")
  vs bare uid distinction lives in exactly one place.
"""
import os

# Must run before the app package is imported (it reads these at import time).
os.environ["SOCKETIO_MESSAGE_QUEUE"] = ""
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")

import pytest  # noqa: E402

from app import create_app, db as _db  # noqa: E402
from app.config import Config  # noqa: E402
from app.models import (  # noqa: E402
    LocalUser,
    Group,
    GroupMembership,
    ComputeServer,
    GroupGpuAccess,
    GroupCpuLimit,
    Project,
    UserSSHKey,
    ContainerInstance,
    Network,
    StaticAddress,
)


def _build_config(tmp_path):
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir(exist_ok=True)
    project_dir = tmp_path / "ansible_project"
    project_dir.mkdir(exist_ok=True)

    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret-key"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        # "basic" so the simulated Socket.IO handshake doesn't trip "strong"
        # session protection and drop the logged-in user inside handlers.
        SESSION_PROTECTION = "basic"
        # Tests run over plain HTTP; a Secure cookie would (in a real browser)
        # not be sent back, so relax it here. Production keeps the secure default.
        SESSION_COOKIE_SECURE = False
        REDIS_HOST = "localhost"
        REDIS_PORT = "6379"
        ANSIBLE_ROLES_PATH = str(roles_dir)
        ANSIBLE_RUNNER_DIR = str(tmp_path / "runner")
        ANSIBLE_PROJECT_DIR = str(project_dir)
        ANSIBLE_CONTAINER_BASE_DIR = "/docker"
        ANSIBLE_SSH_PRIVATE_KEY_FILE = "/dev/null"
        DOCS_DIR = str(tmp_path / "docs")
        PROJECT_STORAGE_DIR = str(tmp_path / "projects")
        LOCAL_BASE_PATH = str(tmp_path / "home")
        DATASETS_BASE_PATH = str(tmp_path / "datasets")
        DATASETS_LOCAL_BASE_PATH = str(tmp_path / "home_datasets")
        CORS_ORIGINS = "http://localhost:3000"

    return TestConfig


# --- Core harness ---------------------------------------------------------

@pytest.fixture
def app(tmp_path):
    """A fresh application + schema per test, app context already pushed.

    Seeds the special ``Admins`` group (id 0): the admin short-circuit in the
    permission service and several routes/CLI commands assume it exists, and it
    is normally created by a migration rather than by ``create_all``.
    """
    application = create_app(_build_config(tmp_path))
    ctx = application.app_context()
    ctx.push()

    _db.create_all()
    _db.session.add(Group(id=0, name="Admins"))
    _db.session.commit()

    try:
        yield application
    finally:
        _db.session.remove()
        _db.drop_all()
        ctx.pop()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


# --- Identity factories ---------------------------------------------------

def _prefixed_id(user_or_id):
    """Normalise a user object / login wrapper / raw string into a prefixed uid."""
    if isinstance(user_or_id, str):
        return user_or_id
    if isinstance(user_or_id, LocalUser):
        return f"local:{user_or_id.id}"
    return user_or_id.get_id()


@pytest.fixture
def make_local_user(db):
    counter = {"n": 0}

    def _make(username=None, password="password123", is_admin=False):
        counter["n"] += 1
        if username is None:
            username = f"user{counter['n']}"
        user = LocalUser(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        if is_admin:
            db.session.add(
                GroupMembership(user_uid=f"local:{user.id}", group_id=0, is_group_admin=True)
            )
            db.session.commit()
        return user

    return _make


@pytest.fixture
def make_server(db):
    counter = {"n": 0}

    def _make(hostname=None, ssh_port=22, gpu_count=4):
        counter["n"] += 1
        if hostname is None:
            hostname = f"cuda{counter['n']:02d}"
        server = ComputeServer(hostname=hostname, ssh_port=ssh_port, gpu_count=gpu_count)
        db.session.add(server)
        db.session.commit()
        return server

    return _make


@pytest.fixture
def make_group(db):
    """Create a Group with optional server access and GPU/CPU rules.

    * ``image_whitelist``: list of role names (stored comma-joined), or None.
    * ``servers``: list of ComputeServer objects to grant access to.
    * ``gpu_rules``: {server_id: "0,1" | "all"}.
    * ``cpu_rules``: {server_id: float | None}  (None == unlimited).
    """
    counter = {"n": 0}

    def _make(name=None, image_whitelist=None, servers=None, gpu_rules=None, cpu_rules=None):
        counter["n"] += 1
        if name is None:
            name = f"group{counter['n']}"
        group = Group(
            name=name,
            image_whitelist=(",".join(image_whitelist) if image_whitelist else None),
        )
        db.session.add(group)
        db.session.flush()  # need group.id for the rules below

        for server in servers or []:
            group.compute_servers.append(server)

        for server_id, allowed in (gpu_rules or {}).items():
            db.session.add(
                GroupGpuAccess(group_id=group.id, compute_server_id=server_id, allowed_gpus=allowed)
            )

        for server_id, limit in (cpu_rules or {}).items():
            db.session.add(
                GroupCpuLimit(group_id=group.id, compute_server_id=server_id, cpu_limit=limit)
            )

        db.session.commit()
        return group

    return _make


@pytest.fixture
def add_member(db):
    def _add(group, user, is_group_admin=False):
        db.session.add(
            GroupMembership(
                user_uid=_prefixed_id(user), group_id=group.id, is_group_admin=is_group_admin
            )
        )
        db.session.commit()

    return _add


# --- Resource factories ---------------------------------------------------
# Persisted domain objects for the route-level ownership/volume packages.
# Identity always flows through ``_prefixed_id`` so the local/ldap distinction
# lives in exactly one place.

@pytest.fixture
def make_project(db):
    counter = {"n": 0}

    def _make(owner, name=None, shares=None):
        counter["n"] += 1
        if name is None:
            name = f"project{counter['n']}"
        # The cc_project_owner_exclusive constraint requires exactly one owner
        # kind. Route tests use local users, so map onto owner_local_user_id.
        if isinstance(owner, LocalUser):
            owner_local_user_id = owner.id
        else:
            # Accept a raw local user id for convenience.
            owner_local_user_id = int(owner)
        project = Project(name=name, owner_local_user_id=owner_local_user_id)
        db.session.add(project)
        db.session.commit()
        return project

    return _make


@pytest.fixture
def make_ssh_key(db):
    counter = {"n": 0}

    def _make(owner, name=None, public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test"):
        counter["n"] += 1
        if name is None:
            name = f"key{counter['n']}"
        # UserSSHKey.user_uid holds the prefixed id ("local:<id>"), matching the
        # sshkeys route which stores current_user.get_id().
        key = UserSSHKey(user_uid=_prefixed_id(owner), name=name, public_key=public_key)
        db.session.add(key)
        db.session.commit()
        return key

    return _make


@pytest.fixture
def make_network(db):
    counter = {"n": 0}

    def _make(name=None, base_ip="192.168.100.0", prefix_size=24, gateway="192.168.100.1"):
        counter["n"] += 1
        if name is None:
            name = f"net{counter['n']}"
        network = Network(
            name=name, base_ip=base_ip, prefix_size=prefix_size, gateway=gateway
        )
        db.session.add(network)
        db.session.commit()
        return network

    return _make


@pytest.fixture
def make_static_address(db):
    counter = {"n": 0}

    def _make(network, servers=None, ip_address=None, mac_address=None, comment=None):
        counter["n"] += 1
        if ip_address is None:
            ip_address = f"192.168.100.{counter['n'] + 9}"
        if mac_address is None:
            mac_address = f"02:00:00:00:00:{counter['n']:02x}"
        address = StaticAddress(
            ip_address=ip_address,
            mac_address=mac_address,
            comment=comment,
            network_id=network.id,
        )
        for server in servers or []:
            address.available_servers.append(server)
        db.session.add(address)
        db.session.commit()
        return address

    return _make


@pytest.fixture
def make_container(db):
    counter = {"n": 0}

    def _make(owner, project, server, status="RUNNING", static_address=None,
              container_name=None, image_name="worker_synced_ubuntu2404_ssh",
              gpus="0", ssh_key=None):
        counter["n"] += 1
        # cc_container_user requires exactly one of user_local_user_id / user_uid.
        kwargs = {}
        if isinstance(owner, LocalUser):
            kwargs["user_local_user_id"] = owner.id
        else:
            kwargs["user_uid"] = _prefixed_id(owner)
        container = ContainerInstance(
            project_id=project.id,
            compute_server_id=server.id,
            image_name=image_name,
            gpus=gpus,
            status=status,
            container_name=container_name or f"container-{counter['n']}",
            ssh_key_id=ssh_key.id if ssh_key else None,
            static_address_id=static_address.id if static_address else None,
            **kwargs,
        )
        db.session.add(container)
        db.session.commit()
        return container

    return _make


# --- Auth helpers ---------------------------------------------------------

@pytest.fixture
def login_as(client):
    """Establish a Flask-Login session for ``user`` without going through
    ``/auth/login`` (so route tests don't drag local/LDAP auth into every case).
    The user_loader still runs each request, exercising the real load_user path.
    """

    def _login(user):
        uid = _prefixed_id(user)
        with client.session_transaction() as session:
            session["_user_id"] = uid
            session["_fresh"] = True
        return uid

    return _login


@pytest.fixture
def client_for(app):
    """Return a factory that gives each user its *own* authenticated client.

    Two subtleties make naive multi-user tests unreliable, both handled here:

    * ``login_as`` re-binds the shared ``client`` fixture's session, which does
      not reliably switch identity a second time within one test. Each call here
      returns a fresh client with an independent session instead.
    * The ``app`` fixture keeps one app context pushed for the whole test, and
      Flask-Login caches the resolved user on ``g._login_user`` within it. Without
      clearing that, the second client's request re-uses the first user. We drop
      the cache on each call so identity is resolved from the new client's
      session.
    """
    from flask import g

    def _client_for(user):
        for attr in ("_login_user", "_cached_user"):
            if hasattr(g, attr):
                delattr(g, attr)
        c = app.test_client()
        with c.session_transaction() as session:
            session["_user_id"] = _prefixed_id(user)
            session["_fresh"] = True
        return c

    return _client_for


@pytest.fixture
def admin_user(app, make_local_user):
    """A local admin (member of the Admins group)."""
    return make_local_user(username="admin", password="password123", is_admin=True)


@pytest.fixture
def admin_client(app, admin_user):
    """A test client with an authenticated admin session via /auth/login."""
    c = app.test_client()
    resp = c.post("/auth/login", json={"username": "admin", "password": "password123"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return c
