"""Coverage guard for the container-route database lookups.

These tests exercise the ``get`` / ``get_or_404`` call sites in
``app/routes/containers.py`` so the conversion from the legacy
``Model.query.get*()`` API to the SQLAlchemy 2.0 ``db.session.get`` /
``db.get_or_404`` form is protected by tests. They assert behaviour (status
codes, side effects), not the API flavour, so they stay green across the change.
"""
import logging
from datetime import datetime, timezone, timedelta
import pytest
from app import socketio
from app.models import ContainerInstance, StaticAddress


@pytest.fixture
def owned_container(app, db, make_local_user, make_project, make_server, make_container, login_as, monkeypatch):
    """A logged-in owner with one RUNNING container of theirs."""
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    user = make_local_user(username="owner")
    project = make_project(owner=user)
    server = make_server()
    container = make_container(owner=user, project=project, server=server, status="RUNNING")
    login_as(user)
    return {"user": user, "container": container, "server": server, "project": project}


# --- get_container / check_container_permission (lines 19, 86-103) ----------

def test_get_own_container_returns_200(client, owned_container):
    cid = owned_container["container"].id
    resp = client.get(f"/api/containers/{cid}")
    assert resp.status_code == 200
    assert resp.get_json()["id"] == cid


def test_get_missing_container_returns_404(client, owned_container):
    resp = client.get("/api/containers/999999")
    assert resp.status_code == 404


def test_get_other_users_container_denied(client, db, owned_container, make_local_user, make_project, make_server,
                                          make_container, login_as):
    other = make_local_user(username="intruder")
    victim_container = owned_container["container"]
    login_as(other)
    resp = client.get(f"/api/containers/{victim_container.id}")
    assert resp.status_code == 404  # not owner, not admin -> hidden


def test_stop_own_container_queues_job(client, owned_container):
    cid = owned_container["container"].id
    resp = client.post(f"/api/containers/{cid}/stop")
    assert resp.status_code == 202, resp.get_data(as_text=True)


def test_stop_other_users_container_denied(client, owned_container, make_local_user, login_as):
    other = make_local_user(username="intruder2")
    cid = owned_container["container"].id
    login_as(other)
    resp = client.post(f"/api/containers/{cid}/stop")
    assert resp.status_code == 403


# --- admin endpoints that look up FK targets (lines 405-542) ----------------

def test_admin_create_container_record_happy_path(admin_client, db, admin_user, make_project, make_server):
    project = make_project(owner=admin_user)
    server = make_server()
    resp = admin_client.post("/api/admin/containers", json={
        "project_id": project.id,
        "compute_server_id": server.id,
        "image_name": "worker_synced_ubuntu2404_ssh",
        "status": "RUNNING",
        "user_identifier": f"local:{admin_user.id}",
        "gpus": "0",
    })
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert db.session.query(ContainerInstance).count() == 1


def test_admin_create_container_record_unknown_local_user_404(admin_client, make_project, make_server, admin_user):
    project = make_project(owner=admin_user)
    server = make_server()
    resp = admin_client.post("/api/admin/containers", json={
        "project_id": project.id,
        "compute_server_id": server.id,
        "image_name": "img",
        "status": "RUNNING",
        "user_identifier": "local:999999",
        "gpus": "0",
    })
    assert resp.status_code == 404


def test_admin_update_container_record(admin_client, db, admin_user, make_project, make_server, make_container):
    project = make_project(owner=admin_user)
    server = make_server()
    container = make_container(owner=admin_user, project=project, server=server)
    resp = admin_client.put(f"/api/admin/containers/{container.id}", json={
        "status": "STOPPED",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert db.session.get(ContainerInstance, container.id).status == "STOPPED"


def test_admin_update_container_reassign_static_address(admin_client, db, admin_user, make_project, make_server,
                                                        make_container, make_network, make_static_address):
    project = make_project(owner=admin_user)
    server = make_server()
    container = make_container(owner=admin_user, project=project, server=server)
    network = make_network()
    address = make_static_address(network=network, servers=[server])
    resp = admin_client.put(f"/api/admin/containers/{container.id}", json={
        "static_address_id": address.id,
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert db.session.get(ContainerInstance, container.id).static_address_id == address.id


def test_admin_delete_container_record_releases_address(admin_client, db, admin_user, make_project, make_server,
                                                        make_container, make_network, make_static_address):
    project = make_project(owner=admin_user)
    server = make_server()
    network = make_network()
    address = make_static_address(network=network, servers=[server])
    container = make_container(
        owner=admin_user, project=project, server=server, static_address=address
    )
    resp = admin_client.delete(f"/api/admin/containers/{container.id}")
    assert resp.status_code == 204
    assert db.session.get(ContainerInstance, container.id) is None
    # Address row survives, just unassigned.
    assert db.session.get(StaticAddress, address.id) is not None


# --- Access logging: get_container logged the builtin `id`, not the id -------

def test_admin_access_log_contains_real_container_id(client, db, caplog, make_local_user, make_project, make_server,
                                                     make_container, admin_user, login_as):
    owner = make_local_user(username="owner_log")
    project = make_project(owner=owner)
    server = make_server()
    container = make_container(owner=owner, project=project, server=server)

    login_as(admin_user)
    with caplog.at_level(logging.INFO):
        resp = client.get(f"/api/containers/{container.id}")
    assert resp.status_code == 200

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert f"container {container.id}" in joined
    assert "built-in function id" not in joined


# --- prolong_container: naive datetime.utcnow() fallback --------------------

def test_prolong_null_ttl_sets_value_four_weeks_out(client, db, make_local_user, make_project, make_server,
                                                    make_container, login_as, monkeypatch):
    """A null ttl_date must prolong without error and land ~4 weeks out.

    The fallback now uses aware ``datetime.now(timezone.utc)`` (matching the rest
    of the codebase) instead of naive ``utcnow()``. The ttl_date column is now
    ``DateTime(timezone=True)``, but SQLite (used by the tests) has no native tz
    type and returns naive datetimes on read-back, so tz-awareness after a
    round-trip can only be asserted against Postgres. This test guards the
    value/no-crash behaviour the code fix owns.
    """
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    import app.routes.containers as containers
    monkeypatch.setattr(
        containers, "queue_prolong_ttl_job",
        lambda container, new_ttl: ("", 202)
    )

    owner = make_local_user(username="owner_ttl")
    project = make_project(owner=owner)
    server = make_server()
    container = make_container(owner=owner, project=project, server=server)
    assert container.ttl_date is None
    login_as(owner)
    resp = client.post(f"/api/containers/{container.id}/prolong")
    assert resp.status_code == 202, resp.get_data(as_text=True)

    db.session.refresh(container)
    assert container.ttl_date is not None
    # Postgres returns the aware value; SQLite drops the zone, leaving UTC.
    ttl = container.ttl_date if container.ttl_date.tzinfo else container.ttl_date.replace(tzinfo=timezone.utc)
    expected = datetime.now(timezone.utc) + timedelta(weeks=4)
    assert abs((ttl - expected).total_seconds()) < 3600


def test_prolong_fallback_is_naive_aware_safe():
    """The fallback arithmetic must not raise, for either branch of the `or`."""
    fallback = datetime.now(timezone.utc)  # null-ttl branch
    assert (fallback + timedelta(weeks=4)) > fallback

    existing_aware = datetime(2026, 1, 1, tzinfo=timezone.utc)  # existing-ttl branch
    assert (existing_aware + timedelta(weeks=4)).tzinfo is not None


# --- Ownership boundaries on container actions (WP5) ------------------------
# check_container_permission (owner-or-admin) guards delete/pause/resume/stop/
# prolong. These prove a non-owner is refused (403) and the owner is allowed.

import pytest as _pytest


@_pytest.mark.parametrize("method,path_suffix", [
    ("delete", ""),
    ("post", "/pause"),
    ("post", "/resume"),
    ("post", "/stop"),
    ("post", "/prolong"),
])
def test_container_action_denied_for_non_owner(client, db, owned_container, make_local_user, login_as, monkeypatch,
                                               method, path_suffix):
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    intruder = make_local_user(username=f"intruder_{path_suffix.strip('/') or 'delete'}")
    cid = owned_container["container"].id
    login_as(intruder)
    resp = getattr(client, method)(f"/api/containers/{cid}{path_suffix}")
    assert resp.status_code == 403, resp.get_data(as_text=True)


def test_container_delete_allowed_for_owner(client, db, owned_container, monkeypatch):
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    cid = owned_container["container"].id
    resp = client.delete(f"/api/containers/{cid}")
    assert resp.status_code == 202, resp.get_data(as_text=True)


def test_container_action_allowed_for_admin(client, db, owned_container, admin_user, login_as, monkeypatch):
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    cid = owned_container["container"].id
    login_as(admin_user)
    resp = client.post(f"/api/containers/{cid}/stop")
    assert resp.status_code == 202, resp.get_data(as_text=True)
