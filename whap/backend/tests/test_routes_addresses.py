"""Regression test for the static-address creation route.

Bug #10: the first validation branch returned ``jsonify({...})`` with no status
code, so a request missing required fields received ``200 OK`` instead of a
client error. Missing fields must produce ``400``.
"""


def test_create_static_address_missing_fields_returns_400(admin_client):
    resp = admin_client.post("/api/admin/static_addresses", json={})
    assert resp.status_code == 400
