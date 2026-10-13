"""Reminders before local project directories expire, notices in WhaP, and the
admin's overview of both (WP6)."""
from datetime import datetime, timedelta, UTC

import pytest

from app.models import Notification, NotificationDelivery, NotificationSettings
from app.notifications import dispatch, expiry

TTL = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)


@pytest.fixture
def carol(db, make_local_user):
    user = make_local_user(username="carol")
    user.email = "carol@uni.example"
    db.session.commit()
    return user


@pytest.fixture
def boxes(db, carol, make_project, make_server, make_container):
    tycho = make_server(hostname="tycho")
    project = make_project(owner=carol, name="ocr")
    local = make_container(carol, project, tycho, image_name="worker_local_ubuntu2404_ssh")
    synced = make_container(carol, project, tycho, image_name="worker_synced_ubuntu2404_ssh")
    gone = make_container(carol, project, tycho, image_name="worker_local_ubuntu2510_ssh", status="DELETED")
    for c in (local, synced, gone):
        c.ttl_date = TTL
    db.session.commit()
    return {"local": local, "synced": synced, "gone": gone, "tycho": tycho}


def reminders(db):
    return db.session.scalars(db.select(Notification).filter_by(kind="expiry").order_by(Notification.id)).all()


def at(days_before, hours=0):
    return TTL - timedelta(days=days_before, hours=hours)


def test_a_reminder_comes_seven_days_and_one_day_before_and_only_once(db, boxes):
    assert expiry.scan(at(8)) == 0, "8 days before: not yet"
    assert expiry.scan(at(7, 1)) == 0, "7 days and an hour before: not yet"
    assert not expiry.due(at(7, 1))
    assert expiry.due(at(7))
    assert expiry.scan(at(7)) == 1
    assert expiry.scan(at(6)) == 0, "no second reminder for the same step"
    assert expiry.scan(at(1)) == 1
    assert expiry.scan(at(0, 1)) == 0
    assert [n.params_dict["days"] for n in reminders(db)] == [7, 1]
    assert {n.params_dict["container_id"] for n in reminders(db)} == {boxes["local"].id}, \
        "synced and deleted containers don't expire"


def test_prolonging_starts_the_reminders_again(db, boxes):
    expiry.scan(at(1))
    boxes["local"].ttl_date = TTL + timedelta(weeks=4)
    db.session.commit()
    assert expiry.scan(at(1)) == 0, "the new date is four weeks away"
    assert expiry.scan(TTL + timedelta(weeks=4) - timedelta(days=7)) == 1


def test_a_container_starting_close_to_its_date_gets_one_reminder_not_two(db, boxes):
    assert expiry.scan(at(3)) == 1
    assert reminders(db)[0].params_dict["days"] == 7
    assert expiry.scan(at(2)) == 0
    assert expiry.scan(at(1)) == 1


def test_nothing_is_sent_after_the_date(db, boxes):
    assert expiry.scan(TTL + timedelta(hours=1)) == 0


def test_the_reminder_tells_what_is_deleted_when_and_links_to_prolong(app, db, boxes, mail):
    app.config.update(WHAP_URL="https://whap.uni.example", TIMEZONE="Europe/Berlin")
    dispatch.run_once(at(7))
    [message] = mail.messages
    assert message["To"] == "carol@uni.example"
    assert message["Subject"] == "[WhaP] Your project “ocr” on tycho expires in 7 days"
    text = message.get_body(("plain",)).get_content()
    assert "the local project directory /home/carol/ocr on tycho will be deleted on Thursday, 22 October 2026." in text
    assert f"https://whap.uni.example/user?tab=containers&prolong={boxes['local'].id}" in text
    assert "You get this because you asked to be reminded before local containers expire." in text


def test_the_last_reminder_says_tomorrow(app, db, boxes, mail):
    app.config.update(TIMEZONE="UTC")
    dispatch.run_once(at(1))
    assert mail.messages[0]["Subject"].endswith("expires tomorrow")


def test_users_who_turned_expiry_reminders_off_get_none(db, boxes, carol, mail):
    db.session.add(NotificationSettings(user_uid=f"local:{carol.id}", topic_expiry=False))
    db.session.commit()
    dispatch.run_once(at(7))
    assert len(reminders(db)) == 1 and db.session.query(NotificationDelivery).count() == 0
    assert mail.messages == []


def test_the_worker_notices_a_due_reminder(db, boxes):
    assert not dispatch.work_due(at(8))
    assert dispatch.work_due(at(7))


# --- notices inside WhaP -------------------------------------------------------------

def test_a_user_sees_maintenance_on_their_servers_and_their_expiring_projects(
        app, client, db, carol, make_project, make_server, make_container, login_as):
    app.config["TIMEZONE"] = "UTC"
    now = datetime.now(UTC)
    tycho, kepler = make_server(hostname="tycho"), make_server(hostname="kepler")
    soon = make_container(carol, make_project(owner=carol, name="ocr"), tycho, image_name="worker_local_ubuntu2404_ssh")
    soon.ttl_date = now + timedelta(hours=20)
    later = make_container(carol, make_project(owner=carol, name="thesis"), tycho,
                           image_name="worker_local_ubuntu2404_ssh")
    later.ttl_date = now + timedelta(days=30)

    def maintenance(server, status="scheduled", end=now + timedelta(days=2)):
        n = Notification(kind="maintenance", status=status, subject="{server} restarts on {start}",
                         notice_until=end)
        n.params_dict = {"server_ids": [server.id], "start": (end - timedelta(hours=1)).isoformat(),
                         "end": end.isoformat(), "impact": "stopped"}
        db.session.add(n)

    maintenance(tycho)
    maintenance(kepler)  # not carol's server
    maintenance(tycho, status="cancelled")
    maintenance(tycho, status="sent", end=now - timedelta(hours=1))  # over
    db.session.commit()

    login_as(carol)
    notices = client.get("/api/notices").get_json()
    assert [n["kind"] for n in notices] == ["maintenance", "expiry"]
    restart, expiring = notices
    assert restart["title"].startswith("tycho restarts on ") and restart["containers"] == ["ocr", "thesis"]
    assert restart["impact"].startswith("your containers are stopped")
    assert (expiring["project"], expiring["expires_in"], expiring["urgent"]) == ("ocr", "tomorrow", True)
    assert expiring["container_id"] == soon.id


def test_notices_need_a_login(client):
    assert client.get("/api/notices").status_code == 401


# --- the admin's overview --------------------------------------------------------------

def test_admins_see_upcoming_and_recent_reminders(app, db, admin_client, carol, make_project, make_server,
                                                  make_container, mail):
    now = datetime.now(UTC)
    tycho = make_server(hostname="tycho")
    box = make_container(carol, make_project(owner=carol, name="ocr"), tycho, image_name="worker_local_ubuntu2404_ssh")
    box.ttl_date = now + timedelta(days=10)
    db.session.commit()
    overview = admin_client.get("/api/admin/notifications/expiry").get_json()
    assert overview["days"] == [7, 1]
    assert [(r["project"], r["step"]) for r in overview["upcoming"]] == [("ocr", 7)], \
        "the 1-day reminder is 9 days away"
    assert overview["recent"] == []

    box.ttl_date = now + timedelta(days=5)
    db.session.commit()
    dispatch.run_once(now)
    overview = admin_client.get("/api/admin/notifications/expiry").get_json()
    [recent] = overview["recent"]
    assert recent["title"] == "Your project “ocr” on tycho expires in 5 days"
    assert recent["deliveries"]["sent"] == 1
    assert [r["step"] for r in overview["upcoming"]] == [1]


def test_the_reminder_preview_uses_the_next_container_to_expire(app, db, admin_client, carol, make_project,
                                                                make_server, make_container, mail):
    assert admin_client.get("/api/admin/notifications/expiry/preview").get_json()["sample"] is False
    box = make_container(carol, make_project(owner=carol, name="ocr"), make_server(hostname="tycho"),
                         image_name="worker_local_ubuntu2404_ssh")
    box.ttl_date = datetime.now(UTC) + timedelta(days=3)
    db.session.commit()
    preview = admin_client.get("/api/admin/notifications/expiry/preview").get_json()
    assert preview["sample"] and preview["username"] == "carol"
    assert preview["subject"] == "[WhaP] Your project “ocr” on tycho expires in 3 days"
