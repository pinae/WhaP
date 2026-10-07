"""Expiry dates of local containers, and prolonging them.

Local containers keep their data on the compute server's SSD; a ttl daemon
there deletes a project once the date in its ttl.txt has passed, or when the
file is missing, the date invalid or too far ahead (docs/03_container_types.md).
Synced containers keep their data on the storage server and never expire.

Bugs this pins:
- Prolong wrote ttl_date.txt into the compose directory, which nothing reads;
  the daemon reads ttl.txt in the project home. Prolonging kept no data.
- Prolong committed the new date before checking the container's state, so a
  refused prolong (409) still moved the date.
- Prolong had no ceiling: clicking on pushed the date past what the daemon
  accepts, which gets the project deleted.
- The API took local containers without a date (an empty ttl.txt) and gave
  synced containers one, which the card then offered to prolong.
- An early failure reported the container as 'failed', a status nothing knows;
  for prolong it turned a running container into it.
"""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import socketio
from app.models import AnsibleJob, ContainerInstance

LOCAL, SYNCED = "worker_local_ubuntu2510_ssh", "worker_synced_ubuntu2510_ssh"


@pytest.fixture
def create_payload(app, db, make_local_user, make_project, make_server, make_network, make_static_address,
                   make_group, add_member, login_as, monkeypatch):
    user = make_local_user(username="ttl_user")
    server = make_server(hostname="tycho", gpu_count=1)
    make_static_address(network=make_network(name="lab-private"), servers=[server])
    add_member(make_group(image_whitelist=["*"], servers=[server], gpu_rules={server.id: "all"}), user)
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    login_as(user)
    return {"projectId": make_project(owner=user, name="thesis").id, "serverId": server.id,
            "gpus": "none", "password": "pw"}


def _in(days):
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.mark.parametrize("ttl, message", [
    (None, "needs an auto-deletion (TTL) date"),
    (_in(-1), "in the past"),
    (_in(400), "at most 12 months ahead"),
    ("soon", "Invalid TTL date format"),
])
def test_a_local_container_needs_a_valid_date(client, db, create_payload, ttl, message):
    resp = client.post("/api/containers", json={**create_payload, "imageName": LOCAL, "ttlDate": ttl})
    assert resp.status_code == 400 and message in resp.get_json()["message"]
    assert db.session.scalar(db.select(db.func.count()).select_from(ContainerInstance)) == 0


def test_a_synced_container_gets_no_date_even_if_sent_one(client, db, create_payload):
    resp = client.post("/api/containers", json={**create_payload, "imageName": SYNCED, "ttlDate": _in(30)})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    container = db.session.scalar(db.select(ContainerInstance))
    assert container.ttl_date is None
    assert "ttl_date" not in json.loads(db.session.scalar(db.select(AnsibleJob)).extravars)


@pytest.fixture
def owned(db, make_local_user, make_project, make_server, make_container, login_as, monkeypatch):
    monkeypatch.setattr(socketio, "emit", lambda *a, **k: None)
    owner = make_local_user(username="prolong_owner")
    login_as(owner)

    def _make(image=LOCAL, status="RUNNING", ttl_days=30):
        container = make_container(owner=owner, project=make_project(owner=owner, name=f"p{status}{image[-8:]}"),
                                   server=make_server(), status=status, image_name=image)
        container.ttl_date = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        db.session.commit()
        return container
    return _make


def _ttl(container):
    ttl = container.ttl_date
    return ttl if ttl.tzinfo else ttl.replace(tzinfo=timezone.utc)


def test_prolonging_adds_four_weeks_and_queues_the_file_update(client, db, owned):
    container = owned()
    before = _ttl(container)
    resp = client.post(f"/api/containers/{container.id}/prolong")
    assert resp.status_code == 202, resp.get_data(as_text=True)
    db.session.refresh(container)
    assert _ttl(container) - before == timedelta(weeks=4)
    job = db.session.scalar(db.select(AnsibleJob).filter_by(action="prolong"))
    assert json.loads(job.extravars) == {"ttl_date": f"{_ttl(container):%Y-%m-%d}"}


@pytest.mark.parametrize("status", ["STARTING", "STOPPING", "ERROR"])
def test_a_refused_prolong_leaves_the_date_alone(client, db, owned, status):
    container = owned(status=status)
    before = _ttl(container)
    assert client.post(f"/api/containers/{container.id}/prolong").status_code == 409
    db.session.refresh(container)
    assert _ttl(container) == before
    assert db.session.scalar(db.select(db.func.count()).select_from(AnsibleJob)) == 0


def test_prolonging_stops_at_twelve_months(client, db, owned):
    container = owned(ttl_days=350)
    before = _ttl(container)
    resp = client.post(f"/api/containers/{container.id}/prolong")
    assert resp.status_code == 400 and "at most 12 months ahead" in resp.get_json()["message"]
    db.session.refresh(container)
    assert _ttl(container) == before


def test_a_synced_container_cannot_be_prolonged(client, db, owned):
    container = owned(image=SYNCED)
    resp = client.post(f"/api/containers/{container.id}/prolong")
    assert resp.status_code == 400 and "Only local containers expire" in resp.get_json()["message"]


# --- The prolong job -------------------------------------------------------------

def _prolong_job(extravars):
    user = SimpleNamespace(username="alice", get_ansible_user_params=lambda: {
        "user": "alice", "user_id": "70001", "group_id": "70000"})
    container = SimpleNamespace(id=2, container_name="alice-thesis-2", status="RUNNING", user=user,
                                project=SimpleNamespace(name="thesis"), directory_path="/docker/x",
                                static_address_id=None)
    return SimpleNamespace(id=9, action="prolong", container=container, server=SimpleNamespace(
        id=3, hostname="tycho", ssh_port=22), status="RUNNING", log="", extravars=extravars, playbook="")


def test_the_prolong_job_writes_the_ttl_file_the_daemon_reads(app, db, monkeypatch, tmp_path):
    pytest.importorskip("ansible_runner")
    import app.services.ansible_service as service
    app.config["ANSIBLE_RUNNER_DIR"] = str(tmp_path)
    monkeypatch.setattr(service.ansible_runner, "run", lambda **config: SimpleNamespace(
        status="successful", rc=0, config=SimpleNamespace(artifact_dir=str(tmp_path))))
    job = _prolong_job(json.dumps({"ttl_date": "2027-02-03"}))

    final_status, _, runner_status, _ = service.execute_ansible_job(job, lambda event: None)

    copy = json.loads(job.playbook)[0]["tasks"][0]["ansible.builtin.copy"]
    assert copy["dest"] == "/home/alice/thesis/ttl.txt"   # as common_tasks/local_directory.yml writes it
    assert copy["content"] == "2027-02-03"
    assert (final_status, runner_status) == ("RUNNING", "successful")


def test_a_prolong_job_that_fails_early_leaves_the_container_as_it_was(app, db):
    pytest.importorskip("ansible_runner")
    from app.services.ansible_service import execute_ansible_job
    final_status, _, runner_status, _ = execute_ansible_job(_prolong_job(None), lambda event: None)
    assert (final_status, runner_status) == ("RUNNING", "failed")
