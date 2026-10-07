"""A container needs a password or an SSH key.

Only the form checked this. A request with neither was accepted, and
ansible_service gave the container a random password nobody was told, so it
could never be logged into.
"""
from datetime import date, timedelta

import pytest

from app import socketio
from app.models import ContainerInstance


@pytest.fixture
def payload(app, db, make_local_user, make_project, make_server, make_network, make_static_address,
            make_group, add_member, login_as, monkeypatch):
    user = make_local_user(username="cred_user")
    server = make_server(hostname="tycho", gpu_count=1)
    make_static_address(network=make_network(name="lab-private"), servers=[server])
    add_member(make_group(image_whitelist=["*"], servers=[server], gpu_rules={server.id: "all"}), user)
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    login_as(user)
    return {"projectId": make_project(owner=user, name="thesis").id, "serverId": server.id,
            "imageName": "worker_local_ubuntu2510_ssh", "gpus": "none", "ttlDate": (date.today() + timedelta(days=30)).isoformat()}


@pytest.mark.parametrize("credentials", [{}, {"password": "", "sshKeyId": None}, {"password": None}])
def test_neither_password_nor_key_is_a_400_and_creates_nothing(client, db, payload, credentials):
    resp = client.post("/api/containers", json={**payload, **credentials})
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert resp.get_json()["message"] == "A password or an SSH key is required."
    assert db.session.scalar(db.select(db.func.count()).select_from(ContainerInstance)) == 0


def test_a_password_alone_is_enough(client, payload):
    resp = client.post("/api/containers", json={**payload, "password": "pw"})
    assert resp.status_code == 201, resp.get_data(as_text=True)


def test_a_key_alone_is_enough(client, db, payload):
    from app.models import UserSSHKey
    user_uid = client.get("/auth/session").get_json()["user"]["id"]
    key = UserSSHKey(user_uid=user_uid, name="laptop", public_key="ssh-ed25519 AAAA test")
    db.session.add(key)
    db.session.commit()
    resp = client.post("/api/containers", json={**payload, "sshKeyId": key.id})
    assert resp.status_code == 201, resp.get_data(as_text=True)
