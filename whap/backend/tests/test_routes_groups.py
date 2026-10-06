"""Route-level tests that group create/update enforce grant-validation.

The heavy matrix lives in test_group_grant_validation.py (the pure helper);
these just prove both handlers call it and surface a 403 on rejection, and that
a within-limits grant succeeds.
"""
import pytest

from app.models import Group


def _make_limited_user(make_local_user, make_group, add_member, make_server):
    """A user who is group-admin of a group granting access to ONE server with
    a limited image whitelist and GPU set -- so they can only grant a subset."""
    server = make_server(hostname="srv-limited")
    group = make_group(
        image_whitelist=["ubuntu"],
        servers=[server],
        gpu_rules={server.id: "0,1"},
    )
    user = make_local_user(username="limited_admin")
    add_member(group, user, is_group_admin=True)
    return user, server


def test_create_group_denied_when_granting_unheld_image(client, db, make_local_user, make_group, add_member,
                                                        make_server, login_as):
    user, server = _make_limited_user(make_local_user, make_group, add_member, make_server)
    login_as(user)
    resp = client.post("/api/groups", json={
        "name": "escalate",
        "image_whitelist": ["ubuntu", "secret-image"],  # secret-image not held
        "accessible_server_ids": [server.id],
    })
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert db.session.scalar(db.select(Group).filter_by(name="escalate")) is None


def test_create_group_denied_when_granting_unheld_gpu(client, db, make_local_user, make_group, add_member, make_server,
                                                      login_as):
    user, server = _make_limited_user(make_local_user, make_group, add_member, make_server)
    login_as(user)
    resp = client.post("/api/groups", json={
        "name": "escalate_gpu",
        "accessible_server_ids": [server.id],
        # holds only GPUs 0,1 -> requesting 2 must be refused, not 500.
        "gpu_access_rules": {str(server.id): "0,2"},
    })
    assert resp.status_code == 403, resp.get_data(as_text=True)


def test_create_group_allowed_within_limits(client, db, make_local_user, make_group, add_member, make_server, login_as):
    user, server = _make_limited_user(make_local_user, make_group, add_member, make_server)
    login_as(user)
    resp = client.post("/api/groups", json={
        "name": "within_limits",
        "image_whitelist": ["ubuntu"],
        "accessible_server_ids": [server.id],
        "gpu_access_rules": {str(server.id): "0"},
    })
    assert resp.status_code == 201, resp.get_data(as_text=True)


def test_update_group_denied_when_granting_unheld_server(client, db, make_local_user, make_group, add_member,
                                                         make_server, login_as):
    user, server = _make_limited_user(make_local_user, make_group, add_member, make_server)
    other_server = make_server(hostname="srv-not-held")
    # The group the user administers (their own membership group is limited);
    # create a target group they admin to update.
    target = make_group(image_whitelist=["ubuntu"], servers=[server])
    add_member(target, user, is_group_admin=True)
    login_as(user)
    resp = client.put(f"/api/groups/{target.id}", json={
        "accessible_server_ids": [server.id, other_server.id],  # other not held
        "members": [{"user_uid": f"local:{user.id}", "is_group_admin": True}],
    })
    assert resp.status_code == 403, resp.get_data(as_text=True)


@pytest.mark.parametrize("make_payload", [
    lambda sid: {"gpu_access_rules": {"srv1": "0"}},
    lambda sid: {"cpu_access_rules": {"srv1": 2}},
    lambda sid: {"accessible_server_ids": ["tycho"]},
    lambda sid: {"cpu_access_rules": {str(sid): "nan"}},
], ids=["gpu-key", "cpu-key", "server-list", "nan-cpu"])
def test_malformed_grants_are_a_400_on_create_and_update(client, db, make_local_user, make_group, add_member,
                                                         make_server, login_as, make_payload):
    """A non-numeric server id used to raise ValueError outside the route's try
    block: a 500. Malformed input is a 400; only refused grants are a 403."""
    user, server = _make_limited_user(make_local_user, make_group, add_member, make_server)
    payload = make_payload(server.id)
    target = make_group(image_whitelist=["ubuntu"], servers=[server])
    add_member(target, user, is_group_admin=True)
    login_as(user)

    created = client.post("/api/groups", json={"name": "malformed", **payload})
    assert created.status_code == 400, created.get_data(as_text=True)
    assert db.session.scalar(db.select(Group).filter_by(name="malformed")) is None

    updated = client.put(f"/api/groups/{target.id}", json={
        **payload, "members": [{"user_uid": f"local:{user.id}", "is_group_admin": True}]})
    assert updated.status_code == 400, updated.get_data(as_text=True)


def test_create_and_update_accept_identical_gpu_payload(client, db, make_local_user, make_group, add_member,
                                                        make_server, login_as):
    """Create and update must accept the SAME gpu_access_rules shape the frontend
    sends for both: {server_id: "csv"} strings. This is the unification guard --
    previously create expected {"allowed_gpus": "..."} dicts and 500'd on the
    frontend's real payload.
    """
    user, server = _make_limited_user(make_local_user, make_group, add_member, make_server)
    login_as(user)

    payload = {
        "name": "unified",
        "image_whitelist": ["ubuntu"],
        "accessible_server_ids": [server.id],
        "gpu_access_rules": {str(server.id): "0,1"},
        "cpu_access_rules": {},
        "members": [{"user_uid": f"local:{user.id}", "is_group_admin": True}],
    }
    created = client.post("/api/groups", json=payload)
    assert created.status_code == 201, created.get_data(as_text=True)
    group_id = created.get_json()["id"]

    # The exact same GPU shape must be accepted on update.
    updated = client.put(f"/api/groups/{group_id}", json={
        **payload,
        "gpu_access_rules": {str(server.id): "0"},
    })
    assert updated.status_code == 200, updated.get_data(as_text=True)

    # And the persisted rule reads back as the csv string the frontend expects.
    body = updated.get_json()
    rules = body.get("gpu_access_rules", {})
    # to_dict() serialises as {compute_server_id: "csv"}.
    assert str(server.id) in {str(k) for k in rules.keys()}
    assert list(rules.values()) == ["0"], rules
