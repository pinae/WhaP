import json
from pathlib import Path
from .. import db
from ..models import FileOperationJob

def enqueue_create_directory(path: Path, user, mode=None):
    """Enqueues a job to create a directory (see local_file_service.create_directory)."""
    payload = {
        'path': str(path),
        'user_identifier': user.get_id(),
        'mode': mode,
    }
    job = FileOperationJob(
        operation='create_directory',
        payload=json.dumps(payload)
    )
    db.session.add(job)
    db.session.commit()
    return job

def enqueue_rename_directory(old_path: Path, new_path: Path, user):
    """Enqueues a job to rename a directory."""
    payload = {
        'old_path': str(old_path),
        'new_path': str(new_path),
        'user_identifier': user.get_id()
    }
    job = FileOperationJob(
        operation='rename_directory',
        payload=json.dumps(payload)
    )
    db.session.add(job)
    db.session.commit()
    return job

def enqueue_delete_directory(path: Path):
    """Enqueues a job to delete a directory."""
    payload = {'path': str(path)}
    job = FileOperationJob(
        operation='delete_directory',
        payload=json.dumps(payload)
    )
    db.session.add(job)
    db.session.commit()
    return job

def enqueue_ensure_lines_in_file(file_path: Path, lines: list, user):
    """Enqueues a job to ensure lines exist in a file."""
    payload = {
        'file_path': str(file_path),
        'lines': lines,
        'user_identifier': user.get_id()
    }
    job = FileOperationJob(
        operation='ensure_lines_in_file',
        payload=json.dumps(payload)
    )
    db.session.add(job)
    db.session.commit()
    return job
