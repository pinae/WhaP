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
