"""Tests for app.services.task_queue_service.

Each enqueue_* function persists a FileOperationJob with a given operation and a
JSON payload, then returns it. These are the hand-off point between the request
handlers and the file-operation worker, so the operation name and payload shape
are a contract worth pinning.
"""
import json

from app.services import task_queue_service as tqs
from app.models import FileOperationJob
from app.user_management import LocalUserWrapper


def _user(make_local_user, name):
    return LocalUserWrapper(make_local_user(username=name))


def _only_job(db):
    jobs = db.session.scalars(db.select(FileOperationJob)).all()
    assert len(jobs) == 1
    return jobs[0]


def test_enqueue_create_directory(app, db, make_local_user):
    user = _user(make_local_user, "tqs_create")
    job = tqs.enqueue_create_directory("/data/projects/alice/proj", user)

    persisted = _only_job(db)
    assert persisted is job
    assert persisted.operation == "create_directory"
    assert persisted.status == "PENDING"
    payload = json.loads(persisted.payload)
    assert payload == {
        "path": "/data/projects/alice/proj",
        "user_identifier": user.get_id(),
    }


def test_enqueue_rename_directory(app, db, make_local_user):
    user = _user(make_local_user, "tqs_rename")
    job = tqs.enqueue_rename_directory("/data/old", "/data/new", user)

    persisted = _only_job(db)
    assert persisted is job
    assert persisted.operation == "rename_directory"
    payload = json.loads(persisted.payload)
    assert payload == {
        "old_path": "/data/old",
        "new_path": "/data/new",
        "user_identifier": user.get_id(),
    }


def test_enqueue_delete_directory(app, db):
    # No user for delete.
    job = tqs.enqueue_delete_directory("/data/projects/alice/proj")

    persisted = _only_job(db)
    assert persisted is job
    assert persisted.operation == "delete_directory"
    assert json.loads(persisted.payload) == {"path": "/data/projects/alice/proj"}


def test_enqueue_ensure_lines_in_file(app, db, make_local_user):
    user = _user(make_local_user, "tqs_lines")
    lines = ["ssh-rsa AAA", "ssh-rsa BBB"]
    job = tqs.enqueue_ensure_lines_in_file("/home/alice/.ssh/authorized_keys", lines, user)

    persisted = _only_job(db)
    assert persisted is job
    assert persisted.operation == "ensure_lines_in_file"
    payload = json.loads(persisted.payload)
    assert payload == {
        "file_path": "/home/alice/.ssh/authorized_keys",
        "lines": lines,
        "user_identifier": user.get_id(),
    }


def test_enqueue_accepts_path_objects(app, db, make_local_user):
    """Callers pass pathlib.Path; the payload must serialise them as strings."""
    from pathlib import Path
    user = _user(make_local_user, "tqs_path")
    tqs.enqueue_create_directory(Path("/data") / "projects" / "bob" / "p", user)

    payload = json.loads(_only_job(db).payload)
    assert payload["path"] == "/data/projects/bob/p"
    assert isinstance(payload["path"], str)


def test_enqueue_persists_independent_jobs(app, db, make_local_user):
    user = _user(make_local_user, "tqs_multi")
    tqs.enqueue_create_directory("/a", user)
    tqs.enqueue_delete_directory("/b")

    ops = sorted(j.operation for j in db.session.scalars(db.select(FileOperationJob)).all())
    assert ops == ["create_directory", "delete_directory"]
