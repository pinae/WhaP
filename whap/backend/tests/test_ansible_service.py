"""Regression tests for ``ansible_service.execute_ansible_job`` return arity.

Bug #2: several early-return paths returned a 2-tuple while ``run_job.py``
unpacks the result as a 4-tuple ``(final_status, final_log, runner_status,
extra_data)``. Any of those paths raised ``ValueError: not enough values to
unpack`` in the worker. Every exit must return a 4-tuple.

``ansible_runner`` is imported at module load, so these tests are skipped in
environments where it is not installed (e.g. the authoring sandbox); they run
in the real backend environment.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("ansible_runner")

from app.services.ansible_service import execute_ansible_job  # noqa: E402


def _noop_callback(_event):
    return None


def test_missing_container_or_server_returns_four_tuple(app, db):
    job = SimpleNamespace(
        id=1, action="create", container=None, server=None, status="PENDING", log=""
    )

    result = execute_ansible_job(job, _noop_callback)

    assert isinstance(result, tuple) and len(result) == 4
    final_status, _log, runner_status, extra = result
    assert final_status == "ERROR"
    assert runner_status == "failed"
    assert extra == {}


def test_unsupported_action_returns_four_tuple(app, db):
    container = SimpleNamespace(id=2)
    server = SimpleNamespace(id=3, hostname="node1")
    job = SimpleNamespace(
        id=4, action="bogus", container=container, server=server, status="PENDING", log=""
    )

    result = execute_ansible_job(job, _noop_callback)

    assert isinstance(result, tuple) and len(result) == 4
    final_status, _log, runner_status, _extra = result
    assert final_status == "ERROR"
    assert runner_status == "failed"


def test_playbook_and_runner_data_live_under_ansible_runner_dir(app, db, monkeypatch, tmp_path):
    """Both used to be built from ANSIBLE_PROJECT_DIR, ignoring ANSIBLE_RUNNER_DIR."""
    import os
    import app.services.ansible_service as service

    runner_dir = tmp_path / "configured-runner-dir"
    app.config["ANSIBLE_RUNNER_DIR"] = str(runner_dir)
    seen = {}

    def fake_run(**config):
        seen.update(config)
        seen["playbook_existed"] = os.path.exists(config["playbook"])
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / "stdout").write_text("PLAY RECAP\n")
        return SimpleNamespace(status="successful", rc=0, config=SimpleNamespace(artifact_dir=str(artifacts)))

    monkeypatch.setattr(service.ansible_runner, "run", fake_run)
    container = SimpleNamespace(id=2, container_name="e2e-alice-thesis-2", status="RUNNING",
                                directory_path="/docker/x", static_address_id=None)
    job = SimpleNamespace(id=9, action="stop", container=container, server=SimpleNamespace(
        id=3, hostname="tycho", ssh_port=22), status="RUNNING", log="", extravars=None, playbook="")

    final_status, log, runner_status, _ = execute_ansible_job(job, _noop_callback)

    assert (final_status, runner_status) == ("STOPPED", "successful")
    assert seen["playbook"] == str(runner_dir / "playbooks" / "stop_3_2_9.yml")
    assert seen["playbook_existed"]                      # written before the run...
    assert not os.path.exists(seen["playbook"])          # ...and cleaned up after
    assert seen["private_data_dir"] == str(runner_dir / "job_9")
    assert "PLAY RECAP" in log


def test_what_the_job_process_writes_is_committed(app, db, monkeypatch, tmp_path, make_local_user, make_project,
                                                    make_server, make_network, make_static_address):
    """execute_ansible_job opened a nested app context, so its db.session.commit()
    committed a fresh, empty session while the job and container it changed
    belonged to the caller's, which run_job.py never commits. Every write was
    lost when the worker exited: the log a reconnecting browser is replayed,
    the playbook, and -- worst -- the container name, so a container whose
    creation failed could never be deleted (the delete playbook got None).
    """
    import json
    import app.services.ansible_service as service
    from app.models import AnsibleJob, ContainerInstance

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "stdout").write_text("PLAY RECAP\ntycho : failed=1\n")
    monkeypatch.setattr(service.ansible_runner, "run", lambda **config: SimpleNamespace(
        status="failed", rc=2, config=SimpleNamespace(artifact_dir=str(artifacts))))

    owner = make_local_user(username="alice")
    server = make_server(hostname="tycho", gpu_count=1)
    address = make_static_address(make_network(name="lab"), servers=[server])
    container = ContainerInstance(user_local_user_id=owner.id, project_id=make_project(owner, name="thesis").id,
                                  compute_server_id=server.id, image_name="worker_local_ubuntu2510_ssh", gpus="0",
                                  status="STARTING", static_address_id=address.id)
    db.session.add(container)
    db.session.flush()
    job = AnsibleJob(container_instance_id=container.id, server_id=server.id, status="RUNNING", action="create",
                     extravars=json.dumps({"container_password": "pw"}))
    db.session.add(job)
    db.session.commit()
    job_id, container_id = job.id, container.id

    execute_ansible_job(db.session.get(AnsibleJob, job_id), _noop_callback)
    db.session.remove()  # what the worker process exiting does to anything uncommitted

    job = db.session.get(AnsibleJob, job_id)
    container = db.session.get(ContainerInstance, container_id)
    assert job.log.startswith("Starting Ansible job for action: create")
    assert "--- Playbook Content ---" in job.log
    assert job.log.count("--- Ansible STDOUT ---") == 1 and "PLAY RECAP" in job.log
    assert job.playbook and json.loads(job.playbook)[0]["hosts"] == "tycho"
    assert job.status == "FAILED"
    assert container.container_name == f"alice-thesis-{container_id}"  # so it can be deleted
    assert container.static_address_id is None                         # released on failure
