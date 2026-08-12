"""End-to-end CPU-limit aggregation across multiple group memberships.

Uses the shared ``app``/``db`` fixtures from conftest (the local app/TestConfig
fixtures this file used to carry were removed during consolidation).
"""
from app import db
from app.models import LocalUser, Group, GroupMembership, ComputeServer, GroupCpuLimit
from app.services.permissions_service import get_user_permissions


def test_cpu_limit_aggregation(app):
    server1 = ComputeServer(hostname="server1", ssh_port=22, gpu_count=4)
    db.session.add(server1)
    db.session.commit()

    user = LocalUser(username="testuser")
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    user_uid = f"local:{user.id}"

    # Group 1: limit 0.5
    group1 = Group(name="Group1")
    db.session.add(group1)
    db.session.commit()
    db.session.add(GroupCpuLimit(group_id=group1.id, compute_server_id=server1.id, cpu_limit=0.5))
    group1.compute_servers.append(server1)
    db.session.add(GroupMembership(user_uid=user_uid, group_id=group1.id))
    db.session.commit()

    perms = get_user_permissions(user_uid)
    assert server1.id in perms["cpu_limits"]
    assert perms["cpu_limits"][server1.id] == 0.5

    # Group 2: limit 2.0 -> max(0.5, 2.0) == 2.0
    group2 = Group(name="Group2")
    db.session.add(group2)
    db.session.commit()
    db.session.add(GroupCpuLimit(group_id=group2.id, compute_server_id=server1.id, cpu_limit=2.0))
    group2.compute_servers.append(server1)
    db.session.add(GroupMembership(user_uid=user_uid, group_id=group2.id))
    db.session.commit()

    perms = get_user_permissions(user_uid)
    assert perms["cpu_limits"][server1.id] == 2.0

    # Group 3: unlimited (None) -> dominates -> None
    group3 = Group(name="Group3")
    db.session.add(group3)
    db.session.commit()
    db.session.add(GroupCpuLimit(group_id=group3.id, compute_server_id=server1.id, cpu_limit=None))
    group3.compute_servers.append(server1)
    db.session.add(GroupMembership(user_uid=user_uid, group_id=group3.id))
    db.session.commit()

    perms = get_user_permissions(user_uid)
    assert perms["cpu_limits"][server1.id] is None
