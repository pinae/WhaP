"""The data the notification feature keeps: user settings, notifications,
deliveries and container mounts (WP1)."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    ContainerMount, Notification, NotificationDelivery, NotificationSettings, NOTIFICATION_KINDS,
)
from app.services.notification_service import get_user_email
from app.services.volume_service import dataset_name


# --- settings --------------------------------------------------------------

def test_a_user_without_settings_gets_email_about_everything(db):
    settings = NotificationSettings.for_user("ldap:alice")
    assert settings.channels() == ["email"]
    assert all(settings.wants(kind) for kind in NOTIFICATION_KINDS)
    assert settings.protects_data()
    assert db.session.get(NotificationSettings, "ldap:alice") is None, "defaults are not saved"


def test_saved_settings_are_read_back(db):
    db.session.add(NotificationSettings(user_uid="ldap:alice", topic_image=False))
    db.session.commit()
    settings = NotificationSettings.for_user("ldap:alice")
    assert not settings.wants("image")
    assert settings.wants("dataset") and settings.wants("maintenance")
    assert settings.to_dict()["topics"] == {
        "maintenance": True, "expiry": True, "image": False, "dataset": True,
    }


def test_announcements_reach_users_who_switched_every_topic_off():
    settings = NotificationSettings(user_uid="ldap:alice", topic_maintenance=False, topic_expiry=False,
                                    topic_image=False, topic_dataset=False)
    assert settings.wants("announcement")
    assert not any(settings.wants(kind) for kind in ("maintenance", "expiry", "image", "dataset"))


def test_matrix_counts_as_a_channel_only_once_verified():
    settings = NotificationSettings(user_uid="ldap:alice", email_enabled=False, matrix_enabled=True,
                                    matrix_pending_id="@alice:example.org")
    assert settings.channels() == []
    settings.matrix_id, settings.matrix_room_id = "@alice:example.org", "!room:example.org"
    assert settings.channels() == ["matrix"]


@pytest.mark.parametrize("changes, protected", [
    ({}, True),
    ({"email_enabled": False}, False),
    ({"topic_maintenance": False}, True),
    ({"topic_maintenance": False, "topic_expiry": False}, False),
    ({"topic_image": False, "topic_dataset": False}, True),
])
def test_whap_can_warn_a_user_unless_channels_or_both_data_topics_are_off(changes, protected):
    assert NotificationSettings(user_uid="ldap:alice", **changes).protects_data() is protected


# --- notifications and deliveries ----------------------------------------

def test_a_notification_keeps_its_fields_as_json(db):
    notification = Notification(kind="maintenance", subject="tycho restarts", body="Hello {name}")
    notification.params_dict = {"server_ids": [1], "impact": "stopped"}
    db.session.add(notification)
    db.session.commit()
    assert notification.status == "draft"
    assert db.session.get(Notification, notification.id).to_dict()["params"] == {
        "server_ids": [1], "impact": "stopped"}


def test_each_user_gets_a_notification_once_per_channel_and_phase(db):
    notification = Notification(kind="announcement", subject="s", body="b")
    db.session.add(notification)
    db.session.flush()
    db.session.add_all([
        NotificationDelivery(notification_id=notification.id, user_uid="ldap:alice", channel="email"),
        NotificationDelivery(notification_id=notification.id, user_uid="ldap:alice", channel="matrix"),
        NotificationDelivery(notification_id=notification.id, user_uid="ldap:alice", channel="email",
                             phase="reminder"),
    ])
    db.session.commit()
    db.session.add(NotificationDelivery(notification_id=notification.id, user_uid="ldap:alice", channel="email"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_a_system_notification_is_created_only_once(db):
    db.session.add(Notification(kind="expiry", dedupe_key="expiry:1:2026-10-15:7"))
    db.session.commit()
    db.session.add(Notification(kind="expiry", dedupe_key="expiry:1:2026-10-15:7"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_deleting_a_notification_deletes_its_deliveries(db):
    notification = Notification(kind="announcement")
    db.session.add(notification)
    db.session.flush()
    db.session.add(NotificationDelivery(notification_id=notification.id, user_uid="ldap:alice", channel="email"))
    db.session.commit()
    db.session.delete(notification)
    db.session.commit()
    assert db.session.query(NotificationDelivery).count() == 0


@pytest.mark.parametrize("field, value", [("kind", "newsletter"), ("status", "lost")])
def test_unknown_kinds_and_states_are_refused(db, field, value):
    db.session.add(Notification(**{"kind": "announcement", field: value}))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# --- containers ------------------------------------------------------------

def test_a_container_names_its_owner_as_settings_are_keyed(make_local_user, make_project, make_server,
                                                          make_container):
    local = make_local_user()
    server = make_server()
    project = make_project(owner=local)
    assert make_container(local, project, server).owner_identifier == f"local:{local.id}"
    assert make_container("ldap:alice", project, server).owner_identifier == "ldap:alice"


def test_deleting_a_container_record_deletes_its_mounts(db, make_local_user, make_project, make_server,
                                                       make_container):
    user = make_local_user()
    container = make_container(user, make_project(owner=user), make_server())
    container.mounts.append(ContainerMount(host_path="/data/DATASETS/coco", container_path="/mnt", dataset="coco"))
    db.session.commit()
    db.session.delete(container)
    db.session.commit()
    assert db.session.query(ContainerMount).count() == 0


@pytest.mark.parametrize("host_path, expected", [
    ("/data/DATASETS/coco", "coco"),
    ("/data/DATASETS/coco/", "coco"),
    ("/data/DATASETS/coco/train", None),
    ("/data/DATASETS", None),
    ("/data/alice/thesis", None),
    ("/data/DATASETSX/coco", None),
])
def test_a_dataset_is_a_directory_directly_under_the_datasets_path(host_path, expected):
    assert dataset_name(host_path, "/data/DATASETS") == expected


# --- local users' email ------------------------------------------------------

def test_local_users_get_notifications_at_the_address_an_admin_set(db, make_local_user):
    user = make_local_user()
    assert get_user_email(f"local:{user.id}") is None
    user.email = "carol@example.org"
    db.session.commit()
    assert get_user_email(f"local:{user.id}") == "carol@example.org"
    assert get_user_email("local:999") is None
    assert get_user_email("local:not-a-number") is None


def test_admins_set_and_clear_a_local_users_email(admin_client, db):
    created = admin_client.post("/api/admin/users", json={
        "username": "carol", "password": "password123", "email": " carol@example.org "})
    assert created.status_code == 201, created.get_json()
    assert created.get_json()["email"] == "carol@example.org"
    user_id = created.get_json()["id"]

    listed = admin_client.get("/api/admin/users").get_json()
    assert next(u for u in listed if u["id"] == user_id)["email"] == "carol@example.org"

    cleared = admin_client.put(f"/api/admin/users/{user_id}", json={"email": ""})
    assert cleared.status_code == 200 and cleared.get_json()["email"] is None

    untouched = admin_client.put(f"/api/admin/users/{user_id}", json={"username": "carol2"})
    assert untouched.status_code == 200 and untouched.get_json()["email"] is None


@pytest.mark.parametrize("email", ["carol", "carol@", "carol@example", "a b@example.org"])
def test_an_invalid_email_is_refused(admin_client, email):
    resp = admin_client.post("/api/admin/users", json={
        "username": "carol", "password": "password123", "email": email})
    assert resp.status_code == 400
    assert "not an email address" in resp.get_json()["message"]
