"""WP8 - serialization correctness.

to_dict() emitted ``isoformat() + 'Z'``. For a naive UTC value that's fine, but
for a timezone-aware value isoformat() already ends in ``+00:00``, so the result
was the invalid ``...+00:00Z`` that datetime.fromisoformat cannot parse. The
output must be valid ISO-8601 whether the underlying value is naive or aware.

Every timestamp must also carry an explicit zone. The browser parses an ISO
string without one as *local* time, so a naive value serialised with a bare
isoformat() -- as ContainerInstance.ttl_date was -- showed up shifted by the
viewer's UTC offset.
"""
from datetime import datetime, timezone

import pytest

from app.models import (ComputeServer, ContainerInstance, FileOperationJob, LocalUser, Network, Project,
                        StaticAddress, UserSSHKey)

AWARE = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
NAIVE = datetime(2026, 3, 1, 12, 0)  # naive UTC, as SQLite hands it back


def _assert_valid_iso_utc(value):
    assert isinstance(value, str)
    assert not value.endswith("+00:00Z")  # no doubled UTC marker
    assert value.endswith("Z")            # an explicit zone, in one consistent spelling
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed == AWARE


def _container():
    # In the session: to_dict() queries the container's latest Ansible job.
    from app import db
    container = ContainerInstance(image_name="worker_x", gpus="0", status="RUNNING", user_uid="jdoe")
    container.project = Project(name="p", owner_uid="jdoe")
    container.compute_server = ComputeServer(hostname="tycho", ssh_port=22)
    db.session.add(container)
    return container


# (factory, attribute set on it, key in to_dict()) for every datetime the API emits.
FIELDS = [
    (lambda: LocalUser(username="u"), "created_at", "created_at"),
    (lambda: UserSSHKey(name="k", public_key="ssh-ed25519 A"), "created_at", "created_at"),
    (lambda: Project(name="p", owner_uid="jdoe"), "created_at", "created_at"),
    (lambda: StaticAddress(ip_address="10.0.0.2", mac_address="02:00:00:00:00:01",
                           network=Network(name="n", base_ip="10.0.0.0", prefix_size=24, gateway="10.0.0.1")),
     "created_at", "created_at"),
    (lambda: FileOperationJob(operation="create_directory", payload="{}"), "created_at", "created_at"),
    (lambda: FileOperationJob(operation="create_directory", payload="{}"), "updated_at", "updated_at"),
    (_container, "created_at", "created_at"),
    (_container, "updated_at", "updated_at"),
    (_container, "ttl_date", "ttl_date"),
]


@pytest.mark.parametrize("factory, attribute, key", FIELDS, ids=lambda v: v if isinstance(v, str) else "")
@pytest.mark.parametrize("value", [AWARE, NAIVE], ids=["aware", "naive"])
def test_every_datetime_is_serialised_as_utc_with_z(app, factory, attribute, key, value, monkeypatch):
    obj = factory()
    setattr(obj, attribute, value)
    if isinstance(obj, ContainerInstance):  # its username lookup would query LDAP
        monkeypatch.setattr(ContainerInstance, "user", None, raising=False)
    _assert_valid_iso_utc(obj.to_dict()[key])


def test_missing_ttl_date_is_null(app, monkeypatch):
    monkeypatch.setattr(ContainerInstance, "user", None, raising=False)
    assert _container().to_dict()["ttl_date"] is None


def test_to_dict_handles_none_created_at(app):
    user = LocalUser(username="nulldate")
    user.created_at = None
    assert user.to_dict()["created_at"] is None
