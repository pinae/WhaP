"""Regression tests for the database models."""
from app.models import AnsibleJob


def test_ansiblejob_created_at_default_is_callable():
    """Regression (bug #1): ``AnsibleJob.created_at`` must use a *callable* default.

    The original definition was ``default=datetime.now(UTC)``: the expression is
    evaluated once, at import time, so every row received the same process-start
    timestamp. Jobs then could not be ordered by creation time (and the
    ``ContainerInstance.ansible_jobs`` ``order_by(created_at.desc())`` was
    effectively a no-op). The default must be a callable that SQLAlchemy invokes
    per row, e.g. ``default=lambda: datetime.now(UTC)``.
    """
    default = AnsibleJob.__table__.c.created_at.default
    assert default is not None, "created_at should have a default"
    assert default.is_callable, (
        "created_at default must be callable so it is evaluated per row; "
        "a bare datetime.now(UTC) is frozen at import time"
    )
