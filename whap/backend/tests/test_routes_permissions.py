"""Regression test for ``/permissions/my-available-images``.

Bug #5: the route checked ``image_whitelist == '*'``. Once the permissions
service was fixed to always return a list (``['*']`` meaning "all"), that exact
string comparison was never true for an admin, so admins fell through to the
filter branch and received an empty image list. The route must check
``'*' in image_whitelist``.
"""
import os


def test_admin_sees_all_images(admin_client, app):
    roles_path = app.config["ANSIBLE_ROLES_PATH"]
    for role in ("worker_synced_ubuntu2404_ssh", "worker_local_ubuntu2404_ssh"):
        os.makedirs(os.path.join(roles_path, role), exist_ok=True)

    resp = admin_client.get("/api/permissions/my-available-images")
    assert resp.status_code == 200

    ids = {img["id"] for img in resp.get_json()}
    assert {"worker_synced_ubuntu2404_ssh", "worker_local_ubuntu2404_ssh"} <= ids
