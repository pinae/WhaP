"""Admins composing notifications (WP4): choices, recipients, preview, test, drafts,
scheduling, cancelling, and what happens after sending."""
import os
from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

import pytest

from app.models import ContainerMount, Notification, NotificationDelivery, NotificationSettings
from app.notifications import dispatch

URL = "/api/admin/notifications"
FUTURE = datetime.now(UTC) + timedelta(days=7)
DAY = FUTURE.strftime("%Y-%m-%d")


@pytest.fixture
def setup(app, db, admin_user, admin_client, mail, directory, make_server, make_project, make_container,
          make_group, add_member):
    """tycho with alice's and bob's containers, kepler empty; a group 'students' with alice."""
    app.config["TIMEZONE"] = "Europe/Berlin"
    admin_user.email = "admin@uni.example"
    tycho, kepler = make_server(hostname="tycho"), make_server(hostname="kepler")
    alice_box = make_container("ldap:alice", make_project(owner="ldap:alice", name="thesis"), tycho,
                               image_name="worker_local_ubuntu2404_ssh")
    make_container("ldap:bob", make_project(owner="ldap:bob", name="seg"), tycho)
    alice_box.mounts.append(ContainerMount(host_path="/d/coco", container_path="/c", dataset="coco"))
    students = make_group(name="students")
    add_member(students, "ldap:alice")
    db.session.commit()
    return {"tycho": tycho, "kepler": kepler, "students": students, "client": admin_client}


def maintenance(setup, **changes):
    body = {"kind": "maintenance", "subject": "{server} restarts on {start}",
            "body": "Hello {name}\nWhat happens: {impact}\n{containers}",
            "params": {"server_ids": [setup["tycho"].id], "start": f"{DAY}T08:00", "end": f"{DAY}T09:00",
                       "impact": "stopped"}}
    body.update(changes)
    return body


def draft(setup, **changes):
    resp = setup["client"].post(URL, json=maintenance(setup, **changes))
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def test_only_admins_compose(client, make_local_user, login_as):
    login_as(make_local_user())
    for method, path in [("get", URL), ("get", f"{URL}/options"), ("post", f"{URL}/audience"),
                         ("post", URL), ("post", f"{URL}/1/schedule")]:
        assert getattr(client, method)(path, json={}).status_code == 403


# --- choices --------------------------------------------------------------------------

def test_the_composer_offers_servers_images_datasets_and_groups_with_their_reach(app, setup):
    roles = app.config["ANSIBLE_ROLES_PATH"]
    os.makedirs(os.path.join(roles, "worker_synced_ubuntu2510_ssh"))
    os.makedirs(os.path.join(app.config["DATASETS_BASE_PATH"], "imagenet"))
    options = setup["client"].get(f"{URL}/options").get_json()
    assert options["servers"] == [{"id": setup["kepler"].id, "hostname": "kepler", "containers": 0},
                                  {"id": setup["tycho"].id, "hostname": "tycho", "containers": 2}]
    assert {"name": "worker_local_ubuntu2404_ssh", "containers": 1} in options["images"]
    assert {"name": "worker_synced_ubuntu2510_ssh", "containers": 0} in options["images"]
    assert options["datasets"] == [{"name": "coco", "containers": 1}, {"name": "imagenet", "containers": 0}]
    assert {"id": setup["students"].id, "name": "students", "members": 1} in options["groups"]
    assert "{impact}" in options["templates"]["maintenance"]["body"]
    assert options["fields"]["group"] == ["name", "group", "containers"]
    assert options["timezone"] == "Europe/Berlin"
    assert options["channels"] == {"email": True, "matrix": False}


# --- recipients ------------------------------------------------------------------------

def test_the_recipients_show_who_is_reached_and_how(db, setup):
    db.session.add(NotificationSettings(user_uid="ldap:alice", matrix_enabled=True,
                                        matrix_id="@alice:uni.example", matrix_room_id="!dm:x"))
    db.session.commit()
    result = setup["client"].post(f"{URL}/audience", json=maintenance(setup)).get_json()
    assert result["summary"] == {"total": 2, "reached": 1, "email": 1, "matrix": 1,
                                 "unreachable": {"topic_off": 0, "all_off": 0, "no_address": 1}}
    alice, bob = result["recipients"]
    assert alice["channels"] == [{"channel": "email", "address": "alice@uni.example"},
                                 {"channel": "matrix", "address": "@alice:uni.example"}]
    assert alice["containers"][0]["project"] == "thesis" and alice["containers"][0]["server"] == "tycho"
    assert bob["unreachable"] == "no_address"


@pytest.mark.parametrize("change, complaint", [
    ({"kind": "newsletter"}, "kind is one of"),
    ({"params": {"server_ids": [], "start": "2030-01-01T08:00", "end": "2030-01-01T09:00"}}, "at least one server"),
    ({"params": {"server_ids": [999], "start": "2030-01-01T08:00", "end": "2030-01-01T09:00"}}, "No server"),
    ({"params": {"server_ids": [1], "start": "2030-01-01T09:00", "end": "2030-01-01T08:00"}}, "end after"),
    ({"params": {"server_ids": [1], "start": "soon", "end": "2030-01-01T08:00"}}, "not a date"),
    ({"params": {"server_ids": [1], "start": "2030-01-01T08:00", "end": "2030-01-01T09:00",
                 "impact": "explodes"}}, "impact is one of"),
])
def test_incomplete_choices_are_explained(setup, change, complaint):
    resp = setup["client"].post(f"{URL}/audience", json=maintenance(setup, **change))
    assert resp.status_code == 400 and complaint in resp.get_json()["message"]


def test_groups_datasets_and_everyone_can_be_chosen(setup):
    client = setup["client"]
    group = client.post(f"{URL}/audience", json={"kind": "group",
                                                 "params": {"group_ids": [setup["students"].id]}}).get_json()
    dataset = client.post(f"{URL}/audience", json={"kind": "dataset", "params": {"dataset": "coco"}}).get_json()
    everyone = client.post(f"{URL}/audience", json={"kind": "announcement"}).get_json()
    assert [r["username"] for r in group["recipients"]] == ["alice"]
    assert [r["username"] for r in dataset["recipients"]] == ["alice"]
    assert [r["username"] for r in everyone["recipients"]] == ["admin", "alice", "bob"]


def test_an_ldap_outage_is_reported_not_hidden(setup, directory):
    directory["down"] = True
    resp = setup["client"].post(f"{URL}/audience", json=maintenance(setup))
    assert resp.status_code == 503 and "LDAP" in resp.get_json()["message"]


# --- preview and test -------------------------------------------------------------------

def test_the_preview_shows_a_recipients_message_in_the_servers_time_zone(setup):
    preview = setup["client"].post(f"{URL}/preview", json=maintenance(setup)).get_json()
    assert [r["username"] for r in preview["recipients"]] == ["alice", "bob"]
    assert preview["username"] == "alice", "the first one who is reached"
    weekday = datetime.fromisoformat(f"{DAY}T08:00").strftime("%a %-d %b")
    assert preview["email"]["subject"] == f"[WhaP] tycho restarts on {weekday}, 08:00"
    assert preview["email"]["to"] == "alice@uni.example"
    assert "What happens: your containers are stopped before the restart." in preview["email"]["text"]
    assert "thesis (worker_local_ubuntu2404_ssh) on tycho" in preview["email"]["text"]
    assert preview["matrix"]["text"].startswith(f"tycho restarts on {weekday}, 08:00\n\nHello Alice")


def test_the_preview_steps_to_a_chosen_recipient_and_shows_reminders(setup):
    preview = setup["client"].post(f"{URL}/preview", json=maintenance(setup, user_uid="ldap:bob",
                                                                      phase="reminder")).get_json()
    assert preview["username"] == "bob"
    assert preview["email"]["subject"].startswith("[WhaP] Reminder: ")


def test_a_preview_for_nobody_is_written_as_for_the_admin(setup):
    preview = setup["client"].post(f"{URL}/preview", json=maintenance(setup, params={
        "server_ids": [setup["kepler"].id], "start": f"{DAY}T08:00", "end": f"{DAY}T09:00"})).get_json()
    assert preview["recipients"] == [] and preview["username"] == "admin"


def test_the_test_goes_to_the_admin_written_as_for_a_recipient(setup, mail):
    result = setup["client"].post(f"{URL}/test", json=maintenance(setup)).get_json()
    assert result["as_user"] == "alice"
    assert result["results"] == [{"channel": "email", "address": "admin@uni.example", "ok": True}]
    [message] = mail.messages
    assert message["To"] == "admin@uni.example"
    assert message["Subject"].startswith("[WhaP] [Test] tycho restarts on")
    assert "Hello Alice" in message.get_body(("plain",)).get_content()


def test_no_test_for_an_admin_nothing_reaches(db, setup, admin_user):
    admin_user.email = None
    db.session.commit()
    assert setup["client"].post(f"{URL}/test", json=maintenance(setup)).status_code == 400


# --- drafts and scheduling ----------------------------------------------------------------

def test_a_half_written_draft_is_kept(setup):
    saved = draft(setup, subject="", params={"server_ids": []})
    assert saved["status"] == "draft" and saved["editable"]
    assert saved["params"] == {"server_ids": []}
    assert saved["created_by"].startswith("local:")


def test_a_draft_is_changed_and_its_times_read_in_the_servers_zone(setup):
    saved = draft(setup)
    berlin = datetime.fromisoformat(f"{DAY}T08:00").replace(tzinfo=ZoneInfo("Europe/Berlin"))
    assert saved["params"]["start"] == berlin.astimezone(UTC).isoformat()
    changed = setup["client"].put(f"{URL}/{saved['id']}", json={"subject": "New subject"}).get_json()
    assert changed["subject"] == "New subject" and changed["about"] == "tycho"


@pytest.mark.parametrize("change, complaint", [
    ({"subject": " "}, "Write a subject"),
    ({"body": ""}, "Write a message"),
    ({"params": {"server_ids": []}}, "at least one server"),
])
def test_only_a_complete_draft_is_scheduled(setup, change, complaint):
    saved = draft(setup, **change)
    resp = setup["client"].post(f"{URL}/{saved['id']}/schedule", json={})
    assert resp.status_code == 400 and complaint in resp.get_json()["message"]


def test_scheduling_without_a_time_sends_now_and_keeps_the_notice_until_the_end(db, setup):
    saved = draft(setup)
    scheduled = setup["client"].post(f"{URL}/{saved['id']}/schedule", json={}).get_json()
    assert scheduled["status"] == "scheduled" and scheduled["editable"] is True
    assert scheduled["notice_until"] == scheduled["params"]["end"].replace("+00:00", "Z")
    assert dispatch.work_due()


def test_a_reminder_must_fall_between_sending_and_the_maintenance(setup):
    client = setup["client"]
    saved = draft(setup)
    too_late = client.post(f"{URL}/{saved['id']}/schedule", json={"remind_at": f"{DAY}T08:30"})
    assert "before the maintenance starts" in too_late.get_json()["message"]
    early = (FUTURE - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    too_early = client.post(f"{URL}/{saved['id']}/schedule",
                            json={"send_at": f"{DAY}T06:00", "remind_at": early})
    assert "after the notification" in too_early.get_json()["message"]
    ok = client.post(f"{URL}/{saved['id']}/schedule", json={"send_at": early, "remind_at": f"{DAY}T07:00"})
    assert ok.status_code == 200 and ok.get_json()["remind_at"]


def test_a_scheduled_notification_can_be_edited_but_stays_valid_and_can_be_cancelled(setup):
    client = setup["client"]
    saved = draft(setup)
    client.post(f"{URL}/{saved['id']}/schedule", json={"send_at": f"{DAY}T06:00"})
    assert client.put(f"{URL}/{saved['id']}", json={"subject": "Moved"}).get_json()["subject"] == "Moved"
    assert client.put(f"{URL}/{saved['id']}", json={"body": ""}).status_code == 400
    assert client.post(f"{URL}/{saved['id']}/cancel").get_json()["status"] == "cancelled"
    assert client.delete(f"{URL}/{saved['id']}").status_code == 204


def test_scheduled_notifications_are_cancelled_not_deleted(setup):
    saved = draft(setup)
    setup["client"].post(f"{URL}/{saved['id']}/schedule", json={"send_at": f"{DAY}T06:00"})
    assert setup["client"].delete(f"{URL}/{saved['id']}").status_code == 409


# --- after sending ------------------------------------------------------------------------

def sent(setup):
    saved = draft(setup)
    setup["client"].post(f"{URL}/{saved['id']}/schedule", json={})
    dispatch.run_once()
    return saved["id"]


def test_a_sent_notification_reports_its_deliveries_and_is_read_only(setup, mail):
    notification_id = sent(setup)
    client = setup["client"]
    summary = client.get(f"{URL}/{notification_id}").get_json()
    assert summary["status"] == "sent" and not summary["editable"]
    assert summary["deliveries"] == {"pending": 0, "sent": 1, "failed": 0} and summary["recipients"] == 1
    [delivery] = client.get(f"{URL}/{notification_id}/deliveries").get_json()
    assert (delivery["username"], delivery["channel"], delivery["status"]) == ("alice", "email", "sent")
    assert client.put(f"{URL}/{notification_id}", json={"subject": "x"}).status_code == 409
    assert client.post(f"{URL}/{notification_id}/cancel").status_code == 409


def test_failed_deliveries_can_be_retried(db, setup, mail, monkeypatch):
    from notification_fixtures import CONTACTS
    monkeypatch.setitem(CONTACTS, "alice", {"mail": "unknown@uni.example", "name": "Alice"})
    notification_id = sent(setup)
    assert setup["client"].get(f"{URL}/{notification_id}").get_json()["deliveries"]["failed"] == 1
    assert setup["client"].post(f"{URL}/{notification_id}/retry").get_json() == {"retrying": 1}
    [delivery] = db.session.scalars(db.select(NotificationDelivery)).all()
    assert (delivery.status, delivery.attempts) == ("pending", 0)


def test_a_follow_up_goes_to_the_same_people_with_a_new_text(setup, mail):
    notification_id = sent(setup)
    follow_up = setup["client"].post(f"{URL}/{notification_id}/copy", json={"follow_up": True}).get_json()
    assert follow_up["status"] == "draft" and follow_up["about"] == "tycho"
    assert follow_up["subject"] == "Update: {server} restarts on {start}"
    assert follow_up["body"] == "Hello {name},\n\n"
    copy = setup["client"].post(f"{URL}/{notification_id}/copy").get_json()
    assert copy["body"].startswith("Hello {name}\nWhat happens")


def test_the_list_shows_admin_notifications_newest_first_without_expiry_reminders(db, setup):
    first, second = draft(setup, subject="first"), draft(setup, subject="second")
    db.session.add(Notification(kind="expiry", status="sent", subject="thesis expires"))
    db.session.commit()
    listed = setup["client"].get(URL).get_json()
    assert [n["subject"] for n in listed] == ["second", "first"]
    assert [n["subject"] for n in setup["client"].get(f"{URL}?kind=expiry").get_json()] == ["thesis expires"]
    expiry_id = setup["client"].get(f"{URL}?kind=expiry").get_json()[0]["id"]
    assert setup["client"].put(f"{URL}/{expiry_id}", json={"subject": "x"}).status_code == 400
