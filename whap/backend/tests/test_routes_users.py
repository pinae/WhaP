"""Regression tests for the admin user-management routes.

  * #6 - ``admin_create_user`` referenced ``new_user.uid`` (no such attribute);
         creating an admin user raised AttributeError -> 500.
  * #7 - ``admin_delete_user`` referenced ``current_user.local_id`` (no such
         attribute); every delete raised AttributeError -> 500.
  * #8 - ``search_users`` built ``LdapUserCache(... email=...)`` but the model
         has no ``email`` column -> TypeError, so the LDAP cache never filled.
"""
from app.models import LocalUser, GroupMembership, LdapUserCache
from app.services import ldap_service


def test_create_admin_user_creates_admin_membership(admin_client, db):
    resp = admin_client.post(
        "/api/admin/users",
        json={"username": "newadmin", "password": "password123", "is_admin": True},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

    user = db.session.execute(db.select(LocalUser).filter_by(username="newadmin")).scalar_one()
    membership = GroupMembership.query.filter_by(
        user_uid=f"local:{user.id}", group_id=0
    ).first()
    assert membership is not None
    # Parity with CLI `create-admin` / PUT promotion: admins created via this
    # endpoint must also be group-admins of group 0, not just members.
    assert membership.is_group_admin is True


def test_create_plain_user_has_no_admin_membership(admin_client, db):
    resp = admin_client.post(
        "/api/admin/users", json={"username": "plainuser", "password": "password123"}
    )
    assert resp.status_code == 201

    user = db.session.execute(db.select(LocalUser).filter_by(username="plainuser")).scalar_one()
    assert (
            GroupMembership.query.filter_by(user_uid=f"local:{user.id}", group_id=0).first()
            is None
    )


def test_admin_cannot_delete_their_own_account(admin_client, admin_user):
    resp = admin_client.delete(f"/api/admin/users/{admin_user.id}")
    assert resp.status_code == 403


def test_admin_can_delete_another_user(admin_client, db):
    victim = LocalUser(username="victim")
    victim.set_password("password123")
    db.session.add(victim)
    db.session.commit()

    resp = admin_client.delete(f"/api/admin/users/{victim.id}")
    assert resp.status_code == 204


def test_user_search_populates_ldap_cache(admin_client, db, monkeypatch):
    monkeypatch.setattr(
        ldap_service,
        "get_all_users_in_group",
        lambda *a, **k: [{"uid": "jdoe", "full_name": "John Doe", "mail": "j@example.com"}],
        raising=False,
    )

    resp = admin_client.get("/api/users/search?q=jd")
    assert resp.status_code == 200

    cached = db.session.scalar(db.select(LdapUserCache).filter_by(uid="jdoe"))
    assert cached is not None
    # email column is kept for the notification feature; the LDAP 'mail'
    # attribute must be cached.
    assert cached.email == "j@example.com"
    assert any(row["id"] == "ldap:jdoe" for row in resp.get_json())
