"""GPU selection on container creation.

create_container called data.get('gpus').split(',') before validating, so a
request without 'gpus' (or with a list) was a 500. And the frontend sends the
string 'none' when no GPU is ticked, which was stored as gpus='none' and
rendered into the compose file as device_ids: ["none"] -- CPU-only containers
could not start. Indices are now checked against the server's GPU count.

Group GPU rules are deliberately *not* enforced here (yet): the UI offers every
GPU of the server, so enforcing them is a policy change, not a bug fix.
"""
import types

import pytest

from app import socketio
from app.models import ContainerInstance
from app.routes.containers import parse_gpu_request

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
