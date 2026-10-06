"""GPU selection on container creation.

create_container called data.get('gpus').split(',') before validating, so a
request without 'gpus' (or with a list) was a 500. And the frontend sends the
string 'none' when no GPU is ticked, which was stored as gpus='none' and
rendered into the compose file as device_ids: ["none"] -- CPU-only containers
could not start. Indices are now checked against the server's GPU count.

Group GPU rules are enforced too. They were computed but never checked, so
anyone with access to a server could take any of its GPUs. The form shows
every installed GPU and greys out those not in the server's allowed_gpus, which
comes from the same permissions_service.allowed_gpus() the check uses.
"""
import types

import pytest

from app import socketio
from app.models import ContainerInstance
from app.routes.containers import parse_gpu_request
from app.services.permissions_service import allowed_gpus

SERVER = types.SimpleNamespace(hostname="tycho", gpu_count=2)


@pytest.mark.parametrize("raw, expected", [
    (None, []), ("", []), ("none", []), ("NONE", []), ([], []),
    ("0", ["0"]), ("1,0", ["0", "1"]), (" 1 , 0 ", ["0", "1"]),
    ("0,0", ["0"]), ("01", ["1"]), (["1", 0], ["0", "1"]),
])
def test_valid_requests(raw, expected):
    assert parse_gpu_request(raw, SERVER) == (expected, None)


@pytest.mark.parametrize("raw, message", [
    ("2", "tycho has no GPU 2 (it has 2)"),
    ("0,7", "no GPU 7"),
    ("all", "'all' is not a GPU number"),
    ("-1", "'-1' is not a GPU number"),
    ("²", "'²' is not a GPU number"),     # str.isdigit() would let this through to int()
    ("0,,1", "'' is not a GPU number"),
    (7, "comma-separated list"),
    ({"0": True}, "comma-separated list"),
])
def test_invalid_requests_explain_themselves(raw, message):
    gpus, error = parse_gpu_request(raw, SERVER)
    assert gpus is None and message in error


@pytest.fixture
def create_env(app, db, make_local_user, make_project, make_server, make_network, make_static_address,
               make_group, add_member, login_as, monkeypatch):
    user = make_local_user(username="gpu_user")
    project = make_project(owner=user, name="thesis")
    server = make_server(hostname="tycho", gpu_count=1)
    make_static_address(network=make_network(name="lab-private"), servers=[server])
    group = make_group(image_whitelist=["*"], servers=[server], gpu_rules={server.id: "all"})
    add_member(group, user)
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    login_as(user)
    return {"projectId": project.id, "serverId": server.id, "imageName": "worker_local_ubuntu2510_ssh"}


@pytest.mark.parametrize("payload_gpus", [None, "none", ""])
def test_a_cpu_only_container_is_stored_without_gpus(client, db, create_env, payload_gpus):
    payload = dict(create_env)
    if payload_gpus is not None:
        payload["gpus"] = payload_gpus
    resp = client.post("/api/containers", json=payload)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    container = db.session.scalar(db.select(ContainerInstance))
    assert container.gpus == ""
    # ...which is what ansible_service turns into an empty device list.
    assert (container.gpus.split(',') if container.gpus else []) == []


def test_requested_gpus_are_stored_normalised(client, db, create_env):
    resp = client.post("/api/containers", json={**create_env, "gpus": ["0"]})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert db.session.scalar(db.select(ContainerInstance)).gpus == "0"


@pytest.mark.parametrize("gpus", ["1", "all", 5])
def test_an_invalid_gpu_request_is_a_400_and_creates_nothing(client, db, create_env, gpus):
    resp = client.post("/api/containers", json={**create_env, "gpus": gpus})
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count()).select_from(ContainerInstance)) == 0


# --- GPU permissions ----------------------------------------------------------

FOUR_GPUS = types.SimpleNamespace(id=7, hostname="tycho", gpu_count=4)


@pytest.mark.parametrize("gpu_access, expected", [
    ({7: "all"}, ["0", "1", "2", "3"]),
    ("*", ["0", "1", "2", "3"]),
    ({7: "1,3"}, ["1", "3"]),
    ({7: " 3 , 1 "}, ["1", "3"]),        # rules are stored as typed in the UI
    ({7: "1,9"}, ["1"]),                 # a GPU the server doesn't have is dropped
    ({8: "all"}, []),                    # a rule for another server grants nothing here
    ({}, []),
    (None, []),
])
def test_allowed_gpus(gpu_access, expected):
    assert allowed_gpus({"gpu_access": gpu_access}, FOUR_GPUS) == expected


@pytest.fixture
def partial_env(app, db, make_local_user, make_project, make_server, make_network, make_static_address,
                make_group, add_member, login_as, monkeypatch):
    """A user granted only GPU 1 of a two-GPU server."""
    user = make_local_user(username="gpu1_user")
    project = make_project(owner=user, name="thesis")
    server = make_server(hostname="tycho", gpu_count=2)
    make_static_address(network=make_network(name="lab-private"), servers=[server])
    group = make_group(image_whitelist=["*"], servers=[server], gpu_rules={server.id: "1"})
    add_member(group, user)
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    login_as(user)
    return {"projectId": project.id, "serverId": server.id, "imageName": "worker_local_ubuntu2510_ssh"}


@pytest.mark.parametrize("gpus, status", [("1", 201), ("none", 201), ("0", 403), ("0,1", 403)])
def test_create_enforces_the_users_gpu_rules(client, db, partial_env, gpus, status):
    """Rules used to be computed but never checked: any GPU of an accessible server could be taken."""
    resp = client.post("/api/containers", json={**partial_env, "gpus": gpus})
    assert resp.status_code == status, resp.get_data(as_text=True)
    if status == 403:
        assert "You may not use GPU 0 on tycho. Your groups allow: 1." in resp.get_json()["message"]
        assert db.session.scalar(db.select(db.func.count()).select_from(ContainerInstance)) == 0


def test_a_server_id_sent_as_a_string_is_checked_like_an_int(client, db, partial_env):
    resp = client.post("/api/containers", json={**partial_env, "serverId": str(partial_env["serverId"]),
                                                "gpus": "0"})
    assert resp.status_code == 403, resp.get_data(as_text=True)


def test_the_form_learns_every_installed_gpu_and_which_are_allowed(client, partial_env):
    servers = client.get("/api/permissions/my-available-servers").get_json()
    assert [(s["hostname"], s["gpu_count"], s["allowed_gpus"]) for s in servers] == [("tycho", 2, ["1"])]


def test_admins_may_use_every_gpu(client, db, admin_user, make_server, login_as):
    make_server(hostname="tycho", gpu_count=2)
    login_as(admin_user)
    servers = client.get("/api/permissions/my-available-servers").get_json()
    assert servers[0]["allowed_gpus"] == ["0", "1"]
