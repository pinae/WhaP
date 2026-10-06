"""run_file_op.py, the process that carries out queued file operations."""
import run_file_op
from app.services import local_file_service
from app.services.task_queue_service import enqueue_create_directory
from app.user_management import LocalUserWrapper


def test_create_directory_passes_the_queued_mode_on(app, db, make_local_user, monkeypatch, tmp_path):
    user = LocalUserWrapper(make_local_user(username="fileop_user"))
    with_mode = enqueue_create_directory(tmp_path / "project", user, mode=0o2775).id
    without = enqueue_create_directory(tmp_path / "other", user).id
    seen = {}
    monkeypatch.setattr(run_file_op, "create_app", lambda: app)
    monkeypatch.setattr(local_file_service, "create_directory",
                        lambda path, user, mode=None: seen.setdefault(path.name, mode))

    run_file_op.main(with_mode)
    run_file_op.main(without)

    assert seen == {"project": 0o2775, "other": None}
