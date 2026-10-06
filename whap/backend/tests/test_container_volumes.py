"""WP1 - authorize ``additional_volumes`` host paths on container creation.

Users have root inside their containers, so a bind mount whose ``host_path`` the
user was never granted (``/etc``, ``/``, another user's project dir, or a path
that escapes an allowed root via ``..``) is host compromise / cross-tenant data
theft. ``create_container`` must reject any ``host_path`` not present in the
same allowed set that ``/shared-volumes`` computes, and must do so *before*
allocating an IP or creating any DB rows.

These tests stub only what would otherwise reach the network / Ansible worker
(``socketio.emit``); the authorization decision itself is exercised for real.
"""
import os

import pytest

from app import socketio
from app.models import ContainerInstance, AnsibleJob


@pytest.fixture
def volume_env(app, db, make_local_user, make_project, make_server,
               make_network, make_static_address, make_group, add_member,
               login_as, monkeypatch):
    """A logged-in user with one own project, a server, and a free private IP.

    The user is put in a group that grants access to the server (and all its
    GPUs) so a create request passes the server/GPU permission checks and
    actually reaches the volume-authorization logic under test.

    Also creates the on-disk project directory so a path derived from the user's
    own project is a real directory (``get_gids_for_paths`` / dataset listing use
    the filesystem, and realpath-based checks need the path to resolve).
    """
    user = make_local_user(username="owner")
    project = make_project(owner=user, name="thesis")
    server = make_server(hostname="cuda01")
    network = make_network(name="lab-private")
    make_static_address(network=network, servers=[server])

    group = make_group(
        image_whitelist=["*"],
        servers=[server],
        gpu_rules={server.id: "all"},
    )
    add_member(group, user, is_group_admin=True)

    # Materialise the user's own project dir under PROJECT_STORAGE_DIR so that a
    # request mounting it is a genuine allowed path.
    storage_root = app.config["PROJECT_STORAGE_DIR"]
    own_project_path = os.path.join(storage_root, user.username, project.name)
    os.makedirs(own_project_path, exist_ok=True)

    # Don't let a successful create actually emit over the (disabled) backplane.
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)

    login_as(user)
    return {
        "user": user,
        "project": project,
        "server": server,
        "own_project_path": own_project_path,
    }


def _create_payload(env, additional_volumes):
    return {
        "projectId": env["project"].id,
        "serverId": env["server"].id,
        "imageName": "worker_synced_ubuntu2404_ssh",
        "password": "pw",
        "gpus": "0",
        "additional_volumes": additional_volumes,
    }


def _no_rows(db):
    return (
            db.session.query(ContainerInstance).count() == 0
            and db.session.query(AnsibleJob).count() == 0
    )


def test_create_rejects_unlisted_host_path(client, db, volume_env):
    resp = client.post(
        "/api/containers",
        json=_create_payload(volume_env, [
            {"host_path": "/etc", "container_path": "/mnt/etc", "is_writable": True},
        ]),
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert _no_rows(db), "no container/job should be created on a rejected mount"


def test_create_rejects_parent_traversal(client, db, volume_env):
    # Starts inside an allowed root but escapes it via '..'.
    escaping = os.path.join(volume_env["own_project_path"], "..", "..", "..", "etc")
    resp = client.post(
        "/api/containers",
        json=_create_payload(volume_env, [
            {"host_path": escaping, "container_path": "/mnt/x", "is_writable": True},
        ]),
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert _no_rows(db)


def test_create_rejects_other_users_project_path(client, db, volume_env, make_local_user, make_project, app):
    other = make_local_user(username="victim")
    other_project = make_project(owner=other, name="secret")
    other_path = os.path.join(
        app.config["PROJECT_STORAGE_DIR"], other.username, other_project.name
    )
    os.makedirs(other_path, exist_ok=True)

    resp = client.post(
        "/api/containers",
        json=_create_payload(volume_env, [
            {"host_path": other_path, "container_path": "/mnt/x", "is_writable": True},
        ]),
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert _no_rows(db)


def test_create_allows_listed_host_path(client, db, volume_env):
    resp = client.post(
        "/api/containers",
        json=_create_payload(volume_env, [
            {
                "host_path": volume_env["own_project_path"],
                "container_path": "/mnt/data",
                "is_writable": True,
            },
        ]),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert db.session.query(ContainerInstance).count() == 1


def test_shared_volumes_lists_own_project(client, db, volume_env):
    """The read endpoint and the create-time enforcement share one source of
    truth; this pins the endpoint's output so the refactor can't silently drift.
    """
    resp = client.get("/api/shared-volumes")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    names = [v["name"] for v in resp.get_json()]
    assert "My Project: thesis" in names
    own = next(v for v in resp.get_json() if v["name"] == "My Project: thesis")
    assert own["host_path"] == volume_env["own_project_path"]
    assert own["is_writable"] is True
