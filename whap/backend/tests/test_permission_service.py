"""Tests for ``permissions_service.get_user_permissions``.

Complements ``test_permissions.py`` (CPU-limit aggregation in depth) by pinning
the rest of the aggregation surface: the admin short-circuit, server access,
GPU union/dominance, and image-whitelist behaviour. Uses the shared factories
from ``conftest.py``.

Three of these started life as *characterization* tests that pinned buggy
behaviour; they have been updated to assert the corrected behaviour and are
marked below.
"""
from app.services.permissions_service import get_user_permissions


def _uid(user):
    return f"local:{user.id}"


# --- Admin short-circuit --------------------------------------------------

def test_admin_gets_universal_permissions(make_local_user, make_server):
    admin = make_local_user(is_admin=True)
    s1 = make_server()
    s2 = make_server()

    perms = get_user_permissions(_uid(admin))

    assert sorted(perms["accessible_server_ids"]) == sorted([s1.id, s2.id])
    # Fixed (#3): image_whitelist is now always a list; ['*'] means "all".
    assert perms["image_whitelist"] == ["*"]
    assert perms["gpu_access"] == {s1.id: "all", s2.id: "all"}


def test_admin_permissions_include_cpu_limits_key(make_local_user, make_server):
    """Fixed (#3): the admin branch now returns the same shape as the normal
    branch, including a ``cpu_limits`` entry per server (None == unlimited)."""
    admin = make_local_user(is_admin=True)
    server = make_server()

    perms = get_user_permissions(_uid(admin))

    assert "cpu_limits" in perms
    assert perms["cpu_limits"] == {server.id: None}


# --- No groups ------------------------------------------------------------

def test_user_without_groups_has_empty_permissions(make_local_user):
    user = make_local_user()

    perms = get_user_permissions(_uid(user))

    assert perms["accessible_server_ids"] == []
    assert perms["image_whitelist"] == []
    assert perms["gpu_access"] == {}
    assert perms["cpu_limits"] == {}


# --- Server access --------------------------------------------------------

def test_server_access_is_granted_through_group_membership(make_local_user, make_server, make_group, add_member):
    user = make_local_user()
    server = make_server()
    group = make_group(servers=[server])
    add_member(group, user)

    perms = get_user_permissions(_uid(user))

    assert perms["accessible_server_ids"] == [server.id]


# --- GPU aggregation ------------------------------------------------------

def test_gpu_lists_union_across_groups(make_local_user, make_server, make_group, add_member):
    user = make_local_user()
    server = make_server()
    g1 = make_group(servers=[server], gpu_rules={server.id: "0,1"})
    g2 = make_group(servers=[server], gpu_rules={server.id: "1,2"})
    add_member(g1, user)
    add_member(g2, user)

    perms = get_user_permissions(_uid(user))

    assert perms["gpu_access"][server.id] == "0,1,2"


def test_gpu_all_dominates_specific_lists(make_local_user, make_server, make_group, add_member):
    user = make_local_user()
    server = make_server()
    g1 = make_group(servers=[server], gpu_rules={server.id: "0"})
    g2 = make_group(servers=[server], gpu_rules={server.id: "all"})
    add_member(g1, user)
    add_member(g2, user)

    perms = get_user_permissions(_uid(user))

    assert perms["gpu_access"][server.id] == "all"


def test_gpu_rule_applies_without_compute_server_membership(make_local_user, make_server, make_group, add_member):
    """Fixed (#4): GPU-rule aggregation no longer lives inside the loop over a
    group's ``compute_servers``, so a group can grant GPU access to a server it
    doesn't otherwise list. The rule applies; the server is still not counted as
    "accessible" (that comes only from ``compute_servers``).
    """
    user = make_local_user()
    server = make_server()
    group = make_group(servers=[], gpu_rules={server.id: "0,1"})
    add_member(group, user)

    perms = get_user_permissions(_uid(user))

    assert perms["gpu_access"] == {server.id: "0,1"}
    assert perms["accessible_server_ids"] == []


# --- Image whitelist ------------------------------------------------------

def test_image_whitelist_union_across_groups(make_local_user, make_group, add_member):
    user = make_local_user()
    g1 = make_group(image_whitelist=["worker_a", "worker_b"])
    g2 = make_group(image_whitelist=["worker_b", "worker_c"])
    add_member(g1, user)
    add_member(g2, user)

    perms = get_user_permissions(_uid(user))

    assert perms["image_whitelist"] == ["worker_a", "worker_b", "worker_c"]


def test_image_whitelist_star_dominates(make_local_user, make_group, add_member):
    user = make_local_user()
    g1 = make_group(image_whitelist=["worker_a"])
    g2 = make_group(image_whitelist=["*"])
    add_member(g1, user)
    add_member(g2, user)

    perms = get_user_permissions(_uid(user))

    assert perms["image_whitelist"] == ["*"]


# --- CPU aggregation (one case; full coverage lives in test_permissions.py)

def test_cpu_limit_takes_maximum_across_groups(make_local_user, make_server, make_group, add_member):
    user = make_local_user()
    server = make_server()
    g1 = make_group(servers=[server], cpu_rules={server.id: 0.5})
    g2 = make_group(servers=[server], cpu_rules={server.id: 2.0})
    add_member(g1, user)
    add_member(g2, user)

    perms = get_user_permissions(_uid(user))

    assert perms["cpu_limits"][server.id] == 2.0
