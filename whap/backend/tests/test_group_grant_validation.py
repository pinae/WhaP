"""unit tests for the extracted group grant-validation helper.

A group creator/admin may only grant permissions they themselves hold. This
logic was duplicated (and subtly buggy) across create_my_group / update_my_group,
notably mixing int and str server-id keys against the int-keyed gpu_access map.

``validate_grantable_permissions(user_perms, server_ids, image_whitelist,
gpu_rules, cpu_rules)`` centralises it and returns ``(ok, message)``.

``user_perms`` matches permissions_service.get_user_permissions output:
  accessible_server_ids: list[int] or contains '*'
  image_whitelist:       list[str], ['*'] means all
  gpu_access:            '*' or {int server_id: 'all' | 'csv'}
  cpu_limits:            {int server_id: float | None}   (None == unlimited)

gpu_rules / cpu_rules keys may arrive as str (JSON object keys) or int; the
helper must handle both.
"""
import pytest

from app.services.permissions_service import InvalidGrantRequest, validate_grantable_permissions


def _perms(**over):
    base = dict(
        accessible_server_ids=[1, 2],
        image_whitelist=['ubuntu', 'pytorch'],
        gpu_access={1: 'all', 2: '0,1'},
        cpu_limits={1: 4.0, 2: None},
    )
    base.update(over)
    return base


def ok(*a, **k):
    res = validate_grantable_permissions(*a, **k)
    assert res[0] is True, res[1]


def denied(*a, **k):
    res = validate_grantable_permissions(*a, **k)
    assert res[0] is False
    return res[1]


# --- server access ----------------------------------------------------------

def test_cannot_grant_unheld_server():
    denied(_perms(), server_ids=[3], image_whitelist=[], gpu_rules={}, cpu_rules={})


def test_wildcard_server_grants_anything():
    ok(_perms(accessible_server_ids=['*']), server_ids=[99],
       image_whitelist=[], gpu_rules={}, cpu_rules={})


# --- image whitelist --------------------------------------------------------

def test_cannot_grant_unheld_image():
    denied(_perms(), server_ids=[], image_whitelist=['secret-img'], gpu_rules={}, cpu_rules={})


def test_wildcard_image_allows_all():
    ok(_perms(image_whitelist=['*']), server_ids=[], image_whitelist=['anything'],
       gpu_rules={}, cpu_rules={})


# --- GPU (the int/str key regression) --------------------------------------

def test_gpu_all_access_grants_anything():
    ok(_perms(gpu_access='*'), server_ids=[], image_whitelist=[],
       gpu_rules={'2': '0,1,2,3'}, cpu_rules={})


def test_gpu_subset_allowed_with_str_key():
    # server 2 allows '0,1'; requesting '0' as a STR key must be allowed.
    ok(_perms(), server_ids=[], image_whitelist=[], gpu_rules={'2': '0'}, cpu_rules={})


def test_gpu_subset_allowed_with_int_key():
    ok(_perms(), server_ids=[], image_whitelist=[], gpu_rules={2: '1'}, cpu_rules={})


def test_gpu_superset_denied():
    # server 2 allows only '0,1'; requesting '2' must be denied, not 500.
    denied(_perms(), server_ids=[], image_whitelist=[], gpu_rules={'2': '0,2'}, cpu_rules={})


def test_gpu_on_unheld_server_denied_not_keyerror():
    # server 3 not in gpu_access at all: must be a clean denial, not KeyError.
    denied(_perms(), server_ids=[], image_whitelist=[], gpu_rules={'3': '0'}, cpu_rules={})


def test_gpu_all_server_allows_all_gpus():
    ok(_perms(), server_ids=[], image_whitelist=[], gpu_rules={'1': '0,1,2,7'}, cpu_rules={})


# --- CPU limits -------------------------------------------------------------

def test_cpu_limited_user_cannot_grant_higher():
    denied(_perms(), server_ids=[], image_whitelist=[], gpu_rules={}, cpu_rules={'1': 8.0})


def test_cpu_limited_user_cannot_grant_unlimited():
    denied(_perms(), server_ids=[], image_whitelist=[], gpu_rules={}, cpu_rules={'1': 'unlimited'})


def test_cpu_limited_user_can_grant_equal_or_lower():
    ok(_perms(), server_ids=[], image_whitelist=[], gpu_rules={}, cpu_rules={'1': 4.0})
    ok(_perms(), server_ids=[], image_whitelist=[], gpu_rules={}, cpu_rules={'1': 2.0})


def test_cpu_unlimited_user_can_grant_anything():
    # server 2 limit is None (unlimited) -> may grant unlimited or any number.
    ok(_perms(), server_ids=[], image_whitelist=[], gpu_rules={}, cpu_rules={'2': 'unlimited'})
    ok(_perms(), server_ids=[], image_whitelist=[], gpu_rules={}, cpu_rules={'2': 16.0})


@pytest.mark.parametrize("value", ["abc", "nan", "NaN", "inf", 0, -2])
def test_cpu_malformed_limit_is_invalid_not_denied(value):
    # Malformed input is a 400 (raised), not a 403 (a refused grant). "nan"
    # matters most: every comparison with NaN is false, so it used to slip past
    # the cap and a 4-CPU user could grant "nan".
    with pytest.raises(InvalidGrantRequest, match="CPU limit"):
        validate_grantable_permissions(_perms(), server_ids=[], image_whitelist=[], gpu_rules={},
                                       cpu_rules={'1': value})


# --- malformed server ids (used to be an unhandled ValueError -> 500) --------

@pytest.mark.parametrize("field", ["gpu_rules", "cpu_rules"])
def test_non_numeric_server_id_key_is_invalid(field):
    rules = {"gpu_rules": {}, "cpu_rules": {}}
    rules[field] = {"srv1": "0" if field == "gpu_rules" else 1.0}
    with pytest.raises(InvalidGrantRequest, match="Invalid server ID 'srv1'"):
        validate_grantable_permissions(_perms(), server_ids=[], image_whitelist=[], **rules)


def test_non_numeric_server_id_in_list_is_invalid():
    with pytest.raises(InvalidGrantRequest, match="Invalid server ID 'tycho'"):
        validate_grantable_permissions(_perms(), server_ids=["tycho"], image_whitelist=[], gpu_rules={},
                                       cpu_rules={})


def test_server_id_list_entries_may_be_strings():
    # "1" used to be compared against the int-keyed permissions and denied.
    ok(_perms(), server_ids=["1", 2], image_whitelist=[], gpu_rules={}, cpu_rules={})


def test_cpu_on_unheld_server_denied():
    denied(_perms(), server_ids=[], image_whitelist=[], gpu_rules={}, cpu_rules={'5': 2.0})
