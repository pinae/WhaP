"""Tests for the SSH key routes (app/routes/sshkeys.py).

delete_ssh_key scopes the lookup to the current user
(``filter_by(id=..., user_uid=...).first_or_404()``), so a non-owner gets 404
rather than deleting someone else's key.
"""
from app.models import UserSSHKey


def test_delete_ssh_key_allowed_for_owner(client, db, make_local_user, make_ssh_key, login_as):
    owner = make_local_user(username="key_owner")
    key = make_ssh_key(owner=owner, name="laptop")
    login_as(owner)
    resp = client.delete(f"/api/sshkeys/{key.id}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert db.session.get(UserSSHKey, key.id) is None


def test_delete_ssh_key_denied_for_non_owner(client, db, make_local_user, make_ssh_key, login_as):
    owner = make_local_user(username="key_owner2")
    other = make_local_user(username="key_intruder")
    key = make_ssh_key(owner=owner, name="server")
    login_as(other)
    resp = client.delete(f"/api/sshkeys/{key.id}")
    assert resp.status_code == 404, resp.get_data(as_text=True)
    # Key must survive the denied attempt.
    assert db.session.get(UserSSHKey, key.id) is not None
