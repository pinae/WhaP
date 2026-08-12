"""Regression tests for ``permissions_service.get_user_permissions``.

These guard the two bugs in the permission aggregation:
  * #3 - the admin branch returned a different shape than the normal branch
         (missing ``cpu_limits``; ``image_whitelist`` as a bare ``'*'`` string).
  * #4 - GPU access rules were aggregated *inside* the per-server loop, so a
         group that granted GPU access without listing the server in its
         ``compute_servers`` relationship silently lost the rule.
"""
from app.services import permissions_service
from app.models import (
    Group,
    GroupMembership,
    GroupGpuAccess,
    GroupCpuLimit,
    ComputeServer,
)


def test_admin_permissions_have_uniform_shape(app, db, admin_user):
    """#3: admin result must carry the same keys/types as the normal path."""
    db.session.add(ComputeServer(hostname="gpu-a"))
    db.session.commit()

    perms = permissions_service.get_user_permissions(admin_user.get_user_identifier())

    assert set(perms) == {
        "accessible_server_ids",
        "image_whitelist",
        "gpu_access",
        "cpu_limits",
    }
    assert isinstance(perms["accessible_server_ids"], list)
    assert isinstance(perms["image_whitelist"], list)
    assert "*" in perms["image_whitelist"]
    assert isinstance(perms["gpu_access"], dict)
    assert isinstance(perms["cpu_limits"], dict)


def test_gpu_rule_survives_without_compute_server_membership(app, db):
    """#4: a GPU rule must appear even if the group has no compute_servers."""
    server = ComputeServer(hostname="gpu-b")
    db.session.add(server)
    db.session.commit()

    group = Group(name="vision", image_whitelist="worker_pytorch")
    db.session.add(group)
    db.session.commit()

    # Deliberately do NOT attach `server` to group.compute_servers.
    db.session.add(
        GroupGpuAccess(group_id=group.id, compute_server_id=server.id, allowed_gpus="all")
    )
    db.session.add(GroupMembership(user_uid="local:901", group_id=group.id))
    db.session.commit()

    perms = permissions_service.get_user_permissions("local:901")

    assert perms["gpu_access"].get(server.id) == "all"
    # The server is not "accessible" (not in compute_servers), only GPU-granted.
    assert server.id not in perms["accessible_server_ids"]


def test_non_admin_wildcard_image_whitelist_is_a_list(app, db):
    """A group whitelist of '*' should normalise to the list ['*']."""
    group = Group(name="all-images", image_whitelist="*")
    db.session.add(group)
    db.session.commit()
    db.session.add(GroupMembership(user_uid="local:902", group_id=group.id))
    db.session.commit()

    perms = permissions_service.get_user_permissions("local:902")
    assert perms["image_whitelist"] == ["*"]


def test_cpu_limit_aggregation_takes_max(app, db):
    """Two finite CPU limits on one server aggregate to the maximum."""
    server = ComputeServer(hostname="gpu-c")
    db.session.add(server)
    db.session.commit()

    g1, g2 = Group(name="g1"), Group(name="g2")
    db.session.add_all([g1, g2])
    db.session.commit()
    db.session.add_all(
        [
            GroupCpuLimit(group_id=g1.id, compute_server_id=server.id, cpu_limit=4.0),
            GroupCpuLimit(group_id=g2.id, compute_server_id=server.id, cpu_limit=8.0),
            GroupMembership(user_uid="local:903", group_id=g1.id),
            GroupMembership(user_uid="local:903", group_id=g2.id),
        ]
    )
    db.session.commit()

    perms = permissions_service.get_user_permissions("local:903")
    assert perms["cpu_limits"][server.id] == 8.0


def test_cpu_limit_none_means_unlimited(app, db):
    """A NULL CPU limit (unlimited) wins over any finite limit."""
    server = ComputeServer(hostname="gpu-d")
    db.session.add(server)
    db.session.commit()

    g1, g2 = Group(name="h1"), Group(name="h2")
    db.session.add_all([g1, g2])
    db.session.commit()
    db.session.add_all(
        [
            GroupCpuLimit(group_id=g1.id, compute_server_id=server.id, cpu_limit=4.0),
            GroupCpuLimit(group_id=g2.id, compute_server_id=server.id, cpu_limit=None),
            GroupMembership(user_uid="local:904", group_id=g1.id),
            GroupMembership(user_uid="local:904", group_id=g2.id),
        ]
    )
    db.session.commit()

    perms = permissions_service.get_user_permissions("local:904")
    assert perms["cpu_limits"][server.id] is None
