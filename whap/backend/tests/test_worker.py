"""worker.py, which hands queued jobs to run_job.py and run_file_op.py.

It started every pending job at once. A delete sent while the create was
still running ran beside it; if the create finished last, a container was
left on the compute server that no record knew about. File operations raced
the same way: a rename could overtake the creation of the directory.
"""
import subprocess

import worker
from app.models import AnsibleJob, FileOperationJob


def _job(db, container, action):
    job = AnsibleJob(container_instance_id=container.id, server_id=container.compute_server_id,
                     status="PENDING", action=action)
    db.session.add(job)
    db.session.commit()
    return job


def test_jobs_for_one_container_run_one_at_a_time_in_order(app, db, make_local_user, make_project, make_server,
                                                          make_container):
    owner = make_local_user(username="worker_owner")
    server = make_server()
    first = make_container(owner=owner, project=make_project(owner=owner, name="a"), server=server)
    other = make_container(owner=owner, project=make_project(owner=owner, name="b"), server=server)
    create, delete = _job(db, first, "create"), _job(db, first, "delete")
    elsewhere = _job(db, other, "stop")

    assert worker.next_ansible_job() == create
    create.status = "RUNNING"
    db.session.commit()
    assert worker.next_ansible_job() == elsewhere  # the delete waits; another container's job does not
    elsewhere.status = "RUNNING"
    db.session.commit()
    assert worker.next_ansible_job() is None
    create.status = "SUCCESSFUL"
    db.session.commit()
    assert worker.next_ansible_job() == delete


def test_file_operations_run_in_order_and_a_stuck_one_is_failed(app, db, monkeypatch):
    jobs = [FileOperationJob(operation=op, payload="{}") for op in ("create_directory", "rename_directory")]
    db.session.add_all(jobs)
    db.session.commit()
    ran = []

    def fake_run(args, timeout):
        ran.append(int(args[-1]))
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    while (job := worker.next_file_op()) is not None:
        worker.run_file_op(job)

    assert ran == [jobs[0].id, jobs[1].id]
    assert [db.session.get(FileOperationJob, job.id).status for job in jobs] == ["FAILED", "FAILED"]


def test_jobs_a_previous_worker_left_running_are_failed(app, db, make_local_user, make_project, make_server,
                                                       make_container):
    owner = make_local_user(username="worker_restart")
    container = make_container(owner=owner, project=make_project(owner=owner, name="c"), server=make_server())
    stuck, queued = _job(db, container, "create"), _job(db, container, "delete")
    stuck.status = "RUNNING"
    file_op = FileOperationJob(operation="create_directory", payload="{}", status="RUNNING")
    db.session.add(file_op)
    db.session.commit()

    worker.fail_interrupted_jobs()

    assert stuck.status == "FAILED" and "Interrupted" in stuck.log
    assert file_op.status == "FAILED"
    assert worker.next_ansible_job() == queued  # the delete is no longer held up
