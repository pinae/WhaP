"""Sending notifications (WP2): channels, rendering, recipients, the queue, the worker.

Email goes to a real SMTP server (aiosmtpd) on localhost, so what the tests
check is what a mail server receives. The Matrix homeserver is a fake that
records requests and answers as told. LDAP is replaced by a dictionary.
"""
import email
import socket
from datetime import datetime, timedelta, UTC
from email import policy

import pytest
import requests
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult

from app.models import (
    ContainerMount, LocalUser, Notification, NotificationDelivery, NotificationSettings,
)
from app.notifications import audience, dispatch, render
from app.notifications.email_channel import EmailChannel
from app.notifications.errors import DeliveryError
from app.notifications.matrix_channel import MatrixChannel
from app.services.ldap_service import LdapUnavailable

NOW = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)  # Mon 19 Oct, 08:00 in Berlin

CONTACTS = {
    "alice": {"mail": "alice@uni.example", "name": "Alice"},
    "bob": {"mail": None, "name": "Bob"},
    "dave": {"mail": "dave@uni.example", "name": "Dave"},
    "erin": {"mail": "erin@uni.example", "name": "Erin"},
    "frank": {"mail": "frank@uni.example", "name": "Frank"},
    "unknown": {"mail": "unknown@uni.example", "name": "Unknown"},
    "busy": {"mail": "busy@uni.example", "name": "Busy"},
}


# --- fakes -----------------------------------------------------------------

class MailServer:
    """Accepts mail like a real server; 'unknown@' is refused for good, 'busy@' for now."""

    def __init__(self):
        self.messages = []
        self.logins = []

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if address.startswith("unknown@"):
            return "550 5.1.1 mailbox unavailable"
        if address.startswith("busy@"):
            return "451 4.3.0 try again later"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(email.message_from_bytes(envelope.content, policy=policy.default))
        return "250 OK"

    def authenticate(self, server, session, envelope, mechanism, auth_data):
        self.logins.append((auth_data.login.decode(), auth_data.password.decode()))
        return AuthResult(success=auth_data.password == b"right")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mail(app):
    server = MailServer()
    port = _free_port()
    controller = Controller(server, hostname="127.0.0.1", port=port,
                            authenticator=server.authenticate, auth_require_tls=False)
    controller.start()
    app.config.update(SMTP_SERVER="127.0.0.1", SMTP_PORT=str(port), SMTP_SECURITY="none",
                      SMTP_USERNAME=None, SMTP_PASSWORD=None, SENDER_EMAIL="whap@uni.example",
                      SENDER_NAME="WhaP", WHAP_URL="https://whap.uni.example", TIMEZONE="Europe/Berlin")
    yield server
    controller.stop()


class Reply:
    def __init__(self, status, data=None):
        self.status_code = status
        self.ok = status < 400
        self.data = data

    def json(self):
        if self.data is None:
            raise ValueError("no JSON")
        return self.data


class Homeserver:
    """Records requests; answers with queued replies, else success."""

    def __init__(self):
        self.calls = []
        self.replies = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        reply = self.replies.pop(0) if self.replies else Reply(200, {"event_id": "$event", "room_id": "!new:x"})
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def homeserver(app, monkeypatch):
    server = Homeserver()
    monkeypatch.setattr("app.notifications.matrix_channel.requests.Session", lambda: server)
    app.config.update(MATRIX_HOMESERVER_URL="https://matrix.uni.example", MATRIX_ACCESS_TOKEN="syt_secret")
    return server


@pytest.fixture
def directory(monkeypatch):
    """LDAP as a dictionary: CONTACTS, and everyone() listing them all."""
    state = {"down": False}

    def contacts(uids):
        if state["down"]:
            raise LdapUnavailable("directory down")
        return {uid: CONTACTS[uid] for uid in uids if uid in CONTACTS}

    def everyone():
        return None if state["down"] else [{"uid": uid} for uid in ("alice", "bob")]

    monkeypatch.setattr(audience, "get_ldap_contacts", contacts)
    monkeypatch.setattr(audience, "get_all_users_in_group", everyone)
    return state


@pytest.fixture
def rig(db, make_local_user, make_project, make_server, make_container):
    """tycho with alice's two containers, bob's, carol's (local) and a deleted one; kepler with dave's."""
    tycho, kepler = make_server(hostname="tycho"), make_server(hostname="kepler")
    carol = make_local_user(username="carol")
    carol.email = "carol@uni.example"
    projects = {name: make_project(owner=f"ldap:{name}", name=name) for name in ("alice", "bob", "dave")}
    containers = {
        "alice1": make_container("ldap:alice", projects["alice"], tycho, image_name="worker_local_ubuntu2404_ssh"),
        "alice2": make_container("ldap:alice", projects["alice"], tycho, image_name="worker_synced_ubuntu2510_ssh"),
        "bob": make_container("ldap:bob", projects["bob"], tycho, image_name="worker_local_ubuntu2404_ssh"),
        "carol_box": make_container(carol, make_project(owner=carol, name="ocr"), tycho),
        "gone": make_container("ldap:erin", projects["bob"], tycho, status="DELETED"),
        "dave": make_container("ldap:dave", projects["dave"], kepler, image_name="worker_local_ubuntu2404_ssh"),
    }
    db.session.commit()
    return {"tycho": tycho, "kepler": kepler, "carol": carol, **containers}


def maintenance(db, server, **fields):
    fields.setdefault("status", "scheduled")
    notification = Notification(kind="maintenance", subject="{server} restarts on {start}",
                                body="Hello {name},\n\n{server} restarts {start}–{end}.\n\n{containers}", **fields)
    notification.params_dict = {"server_ids": [server.id], "start": "2026-10-20T06:00:00+00:00",
                                "end": "2026-10-20T07:00:00+00:00", "impact": "stopped"}
    db.session.add(notification)
    db.session.commit()
    return notification


def deliveries(db, **filters):
    return db.session.scalars(db.select(NotificationDelivery).filter_by(**filters)
                              .order_by(NotificationDelivery.id)).all()


# --- email channel -----------------------------------------------------------

def test_an_email_arrives_with_text_html_and_auto_submitted(app, mail):
    with EmailChannel(app.config) as channel:
        channel.send("alice@uni.example", "[WhaP] tycho restarts", "Hello Alice\n", "<p>Hello Alice</p>")
    [message] = mail.messages
    assert message["From"] == "WhaP <whap@uni.example>"
    assert message["To"] == "alice@uni.example"
    assert message["Subject"] == "[WhaP] tycho restarts"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_body(("plain",)).get_content().replace("\r\n", "\n") == "Hello Alice\n"
    assert message.get_body(("html",)).get_content().strip() == "<p>Hello Alice</p>"


def test_whap_logs_in_when_a_username_is_set(app, mail):
    app.config.update(SMTP_USERNAME="whap", SMTP_PASSWORD="right")
    with EmailChannel(app.config) as channel:
        channel.send("alice@uni.example", "s", "t")
    assert mail.logins == [("whap", "right")]
    assert len(mail.messages) == 1


def test_a_wrong_smtp_password_is_not_blamed_on_the_recipients(app, mail, monkeypatch):
    # aiosmtpd holds back its answer to a failed login, so this ends in a timeout.
    monkeypatch.setattr("app.notifications.email_channel.TIMEOUT", 1)
    app.config.update(SMTP_USERNAME="whap", SMTP_PASSWORD="wrong")
    with pytest.raises(DeliveryError) as error:
        EmailChannel(app.config).__enter__()
    assert not error.value.permanent
    assert "wrong" not in str(error.value)


def test_an_unreachable_mail_server_is_a_temporary_failure(app):
    app.config.update(SMTP_SERVER="127.0.0.1", SMTP_PORT=str(_free_port()), SMTP_SECURITY="none",
                      SENDER_EMAIL="whap@uni.example")
    with pytest.raises(DeliveryError) as error:
        EmailChannel(app.config).__enter__()
    assert not error.value.permanent


@pytest.mark.parametrize("address, permanent", [("unknown@uni.example", True), ("busy@uni.example", False)])
def test_a_refused_recipient_fails_for_good_only_on_a_5xx(app, mail, address, permanent):
    with EmailChannel(app.config) as channel:
        with pytest.raises(DeliveryError) as error:
            channel.send(address, "s", "t")
    assert error.value.permanent is permanent


def test_a_malformed_address_fails_that_message_only(app, mail):
    with EmailChannel(app.config) as channel:
        with pytest.raises(DeliveryError) as error:
            channel.send("alice@uni.example\nBcc: everyone@uni.example", "s", "t")
        channel.send("carol@uni.example", "s", "t")
    assert error.value.permanent
    assert [m["To"] for m in mail.messages] == ["carol@uni.example"]


def test_a_subject_is_kept_on_one_line(app, db, rig, directory):
    notification = maintenance(db, rig["tycho"])
    notification.subject = "tycho\nBcc: everyone@uni.example restarts"
    alice = audience.recipients(notification)[0]
    assert render.render(notification, alice, app.config)[0] == "tycho Bcc: everyone@uni.example restarts"


def test_without_smtp_settings_email_is_not_attempted(app):
    app.config.update(SMTP_SERVER=None, SENDER_EMAIL=None)
    with pytest.raises(DeliveryError, match="not configured"):
        EmailChannel(app.config).__enter__()


# --- Matrix channel ------------------------------------------------------------

def test_a_matrix_message_is_posted_once_per_transaction(app, homeserver):
    MatrixChannel(app.config).send("!room:uni.example", "Hello", "<p>Hello</p>", txn_id="whap-delivery-7")
    [call] = homeserver.calls
    assert call["method"] == "PUT"
    assert call["url"] == ("https://matrix.uni.example/_matrix/client/v3/rooms/%21room%3Auni.example"
                           "/send/m.room.message/whap-delivery-7")
    assert call["headers"] == {"Authorization": "Bearer syt_secret"}
    assert call["json"] == {"msgtype": "m.text", "body": "Hello", "format": "org.matrix.custom.html",
                            "formatted_body": "<p>Hello</p>"}


def test_a_direct_chat_invites_the_user(app, homeserver):
    assert MatrixChannel(app.config).create_direct_room("@alice:uni.example") == "!new:x"
    assert homeserver.calls[0]["json"] == {"preset": "trusted_private_chat", "is_direct": True,
                                           "invite": ["@alice:uni.example"], "name": "WhaP"}


@pytest.mark.parametrize("reply, permanent", [
    (Reply(403, {"errcode": "M_FORBIDDEN", "error": "not in room"}), True),
    (Reply(429, {"errcode": "M_LIMIT_EXCEEDED"}), False),
    (Reply(502), False),
    (requests.ConnectionError("refused"), False),
])
def test_matrix_failures_are_permanent_only_when_the_homeserver_refuses(app, homeserver, reply, permanent):
    homeserver.replies.append(reply)
    with pytest.raises(DeliveryError) as error:
        MatrixChannel(app.config).send("!room:x", "Hello")
    assert error.value.permanent is permanent
    assert "syt_secret" not in str(error.value)


# --- rendering -----------------------------------------------------------------

def test_fields_are_filled_and_unknown_braces_left_alone():
    assert render.fill("Hi {name}, {unknown} {}", {"name": "Alice"}) == "Hi Alice, {unknown} {}"


def test_times_are_shown_in_the_configured_zone(app, db, rig, directory):
    notification = maintenance(db, rig["tycho"])
    [alice] = [r for r in audience.recipients(notification) if r.username == "alice"]
    fields = render.fields_for(notification, alice, app.config | {"TIMEZONE": "Europe/Berlin"})
    assert (fields["start"], fields["end"]) == ("Tue 20 Oct, 08:00", "09:00")
    assert fields["server"] == "tycho"
    assert fields["containers"].splitlines() == [
        "  • alice (worker_local_ubuntu2404_ssh) on tycho",
        "  • alice (worker_synced_ubuntu2510_ssh) on tycho",
    ]


def test_html_is_escaped_and_links_work():
    html = render.text_to_html("a <b> & c\nsee https://whap.uni.example/settings.\n\nnext")
    assert html == ('<p>a &lt;b&gt; &amp; c<br>\nsee <a href="https://whap.uni.example/settings">'
                    'https://whap.uni.example/settings</a>.</p>\n<p>next</p>')


def test_every_message_says_why_it_came_and_where_to_change_that(app, db, rig):
    notification = maintenance(db, rig["tycho"])
    message = render.finish(notification, "s", "Body", {"WHAP_URL": "https://whap.uni.example"})
    assert message.text.endswith("You get this because you have containers on tycho. "
                                 "Change what WhaP tells you: https://whap.uni.example/settings\n")
    assert '<a href="https://whap.uni.example/settings">' in message.html


# --- recipients ----------------------------------------------------------------

def test_a_maintenance_notice_concerns_the_owners_of_live_containers_on_the_server(db, rig, directory):
    found = audience.recipients(maintenance(db, rig["tycho"]))
    assert [r.username for r in found] == ["alice", "bob", "carol"]
    alice, bob, carol = found
    assert len(alice.containers) == 2
    assert alice.channels() == [("email", "alice@uni.example")]
    assert carol.channels() == [("email", "carol@uni.example")]
    assert (bob.channels(), bob.unreachable) == ([], "no_address")


def test_settings_decide_who_is_reached(db, rig, directory):
    db.session.add_all([
        NotificationSettings(user_uid="ldap:alice", topic_maintenance=False),
        NotificationSettings(user_uid=f"local:{rig['carol'].id}", email_enabled=False),
    ])
    db.session.commit()
    alice, bob, carol = audience.recipients(maintenance(db, rig["tycho"]))
    assert (alice.unreachable, carol.unreachable) == ("topic_off", "all_off")


def test_a_connected_matrix_account_is_a_second_channel(db, rig, directory):
    db.session.add(NotificationSettings(user_uid="ldap:alice", matrix_enabled=True,
                                        matrix_id="@alice:uni.example", matrix_room_id="!dm:uni.example"))
    db.session.commit()
    alice = audience.recipients(maintenance(db, rig["tycho"]))[0]
    assert alice.channels() == [("email", "alice@uni.example"), ("matrix", "@alice:uni.example")]


def test_image_and_dataset_notices_find_their_users(db, rig, directory):
    image = Notification(kind="image", params='{"image": "worker_local_ubuntu2404_ssh"}')
    rig["bob"].mounts.append(ContainerMount(host_path="/data/DATASETS/coco", container_path="/c", dataset="coco"))
    dataset = Notification(kind="dataset", params='{"dataset": "coco"}')
    db.session.add_all([image, dataset])
    db.session.commit()
    assert [r.username for r in audience.recipients(image)] == ["alice", "bob", "dave"]
    assert [r.username for r in audience.recipients(dataset)] == ["bob"]


def test_an_announcement_reaches_everyone_even_without_containers(db, rig, directory, make_local_user):
    make_local_user(username="zoe")
    found = audience.recipients(Notification(kind="announcement"))
    assert [r.username for r in found] == ["alice", "bob", "carol", "dave", "zoe"]
    db.session.add(NotificationSettings(user_uid="ldap:alice", topic_maintenance=False, topic_expiry=False,
                                        topic_image=False, topic_dataset=False))
    db.session.commit()
    assert audience.recipients(Notification(kind="announcement"))[0].channels() == [("email", "alice@uni.example")]


def test_recipients_are_not_guessed_while_ldap_is_down(db, rig, directory):
    directory["down"] = True
    with pytest.raises(LdapUnavailable):
        audience.recipients(maintenance(db, rig["tycho"]))
    with pytest.raises(LdapUnavailable):
        audience.recipients(Notification(kind="announcement"))


# --- the queue -----------------------------------------------------------------

def test_a_due_notification_becomes_one_rendered_delivery_per_reachable_channel(app, db, rig, directory, mail):
    notification = maintenance(db, rig["tycho"])
    dispatch.dispatch(NOW)
    assert notification.status == "sent"
    rows = deliveries(db)
    assert [(d.user_uid, d.channel, d.address) for d in rows] == [
        ("ldap:alice", "email", "alice@uni.example"),
        (f"local:{rig['carol'].id}", "email", "carol@uni.example"),
    ]
    assert rows[0].subject == "tycho restarts on Tue 20 Oct, 08:00"
    assert rows[0].body.startswith("Hello Alice,\n\ntycho restarts Tue 20 Oct, 08:00–09:00.")


def test_drafts_future_and_cancelled_notifications_wait(db, rig, directory):
    maintenance(db, rig["tycho"], status="draft")
    maintenance(db, rig["tycho"], send_at=NOW + timedelta(hours=1))
    maintenance(db, rig["tycho"], status="cancelled")
    assert not dispatch.work_due(NOW)
    dispatch.dispatch(NOW)
    assert deliveries(db) == []
    assert dispatch.work_due(NOW + timedelta(hours=1))


def test_an_interrupted_dispatch_resumes_without_duplicates(db, rig, directory):
    notification = maintenance(db, rig["tycho"])
    dispatch.queue(notification)  # as if the process died before marking it sent
    db.session.commit()
    notification.status = "sending"
    db.session.commit()
    dispatch.dispatch(NOW)
    assert notification.status == "sent"
    assert len(deliveries(db)) == 2


def test_dispatch_waits_for_ldap_and_keeps_the_notification(db, rig, directory):
    notification = maintenance(db, rig["tycho"])
    directory["down"] = True
    with pytest.raises(LdapUnavailable):
        dispatch.run_once(NOW)
    assert notification.status == "sending" and deliveries(db) == []
    directory["down"] = False
    dispatch.run_once(NOW)
    assert notification.status == "sent"


def test_pending_emails_are_sent_and_recorded(app, db, rig, directory, mail):
    maintenance(db, rig["tycho"])
    dispatch.run_once(NOW)
    assert [m["To"] for m in mail.messages] == ["alice@uni.example", "carol@uni.example"]
    assert mail.messages[0]["Subject"] == "[WhaP] tycho restarts on Tue 20 Oct, 08:00"
    assert "You get this because you have containers on tycho." in mail.messages[0].get_body(("plain",)).get_content()
    assert all(d.status == "sent" and d.sent_at and d.attempts == 1 for d in deliveries(db))
    assert not dispatch.work_due(NOW)


def test_a_temporary_failure_is_retried_twice_then_failed(app, db, rig, directory, mail, monkeypatch):
    monkeypatch.setitem(CONTACTS, "alice", {"mail": "busy@uni.example", "name": "Alice"})
    maintenance(db, rig["tycho"])
    dispatch.run_once(NOW)
    [busy] = deliveries(db, address="busy@uni.example")
    assert (busy.status, busy.attempts, busy.next_attempt_at.replace(tzinfo=UTC)) == (
        "pending", 1, NOW + timedelta(minutes=1))
    assert "451" in busy.last_error

    dispatch.run_once(NOW + timedelta(seconds=30))
    assert busy.attempts == 1, "not before its time"
    dispatch.run_once(NOW + timedelta(minutes=1))
    assert (busy.status, busy.attempts) == ("pending", 2)
    dispatch.run_once(NOW + timedelta(minutes=11))
    assert (busy.status, busy.attempts, busy.next_attempt_at) == ("failed", 3, None)


def test_a_permanent_failure_is_not_retried(app, db, rig, directory, mail, monkeypatch):
    monkeypatch.setitem(CONTACTS, "alice", {"mail": "unknown@uni.example", "name": "Alice"})
    maintenance(db, rig["tycho"])
    dispatch.run_once(NOW)
    [unknown] = deliveries(db, address="unknown@uni.example")
    assert (unknown.status, unknown.attempts) == ("failed", 1)
    assert "550 5.1.1 mailbox unavailable" in unknown.last_error
    assert [m["To"] for m in mail.messages] == ["carol@uni.example"], "the others still go out"


def test_when_the_mail_server_is_down_every_email_waits(app, db, rig, directory):
    app.config.update(SMTP_SERVER="127.0.0.1", SMTP_PORT=str(_free_port()), SMTP_SECURITY="none",
                      SENDER_EMAIL="whap@uni.example")
    maintenance(db, rig["tycho"])
    dispatch.run_once(NOW)
    assert [(d.status, d.attempts) for d in deliveries(db)] == [("pending", 1), ("pending", 1)]


def test_matrix_deliveries_go_to_the_connected_room(app, db, rig, directory, mail, homeserver):
    db.session.add(NotificationSettings(user_uid="ldap:alice", email_enabled=False, matrix_enabled=True,
                                        matrix_id="@alice:uni.example", matrix_room_id="!dm:uni.example"))
    db.session.commit()
    maintenance(db, rig["tycho"])
    dispatch.run_once(NOW)
    [matrix] = deliveries(db, channel="matrix")
    assert matrix.status == "sent"
    [call] = homeserver.calls
    assert "/rooms/%21dm%3Auni.example/send/m.room.message/whap-delivery-" in call["url"]
    assert call["json"]["body"].startswith("tycho restarts on Tue 20 Oct, 08:00\n\nHello Alice,")
    assert call["json"]["formatted_body"].startswith("<p><strong>tycho restarts on Tue 20 Oct, 08:00</strong></p>")


def test_a_matrix_account_disconnected_after_queueing_is_not_written_to(app, db, rig, directory, mail, homeserver):
    settings = NotificationSettings(user_uid="ldap:alice", matrix_enabled=True,
                                    matrix_id="@alice:uni.example", matrix_room_id="!dm:uni.example")
    db.session.add(settings)
    db.session.commit()
    maintenance(db, rig["tycho"])
    dispatch.dispatch(NOW)
    settings.matrix_enabled = False
    db.session.commit()
    dispatch.deliver(NOW)
    [matrix] = deliveries(db, channel="matrix")
    assert (matrix.status, matrix.last_error) == ("failed", "The user disconnected this Matrix account.")
    assert homeserver.calls == []


def test_a_reminder_goes_out_once_at_its_time(app, db, rig, directory, mail):
    maintenance(db, rig["tycho"], remind_at=NOW + timedelta(hours=23))
    dispatch.run_once(NOW)
    dispatch.run_once(NOW + timedelta(hours=22))
    assert len(mail.messages) == 2
    dispatch.run_once(NOW + timedelta(hours=23))
    dispatch.run_once(NOW + timedelta(hours=24))
    assert [m["Subject"] for m in mail.messages[2:]] == [
        "[WhaP] Reminder: tycho restarts on Tue 20 Oct, 08:00"] * 2
    assert len(deliveries(db, phase="reminder")) == 2


# --- the worker ----------------------------------------------------------------

class FakeProcess:
    def __init__(self):
        self.status = None

    def poll(self):
        return self.status


def test_the_worker_starts_one_sender_at_a_time_and_backs_off_after_a_failure(app, monkeypatch):
    import worker
    clock = {"t": 0}
    started = []
    due = {"value": True}
    monkeypatch.setattr(worker.dispatch, "work_due", lambda: due["value"])

    def popen(args):
        started.append(FakeProcess())
        return started[-1]

    notifier = worker.Notifier(clock=lambda: clock["t"], popen=popen)
    notifier.tick()
    assert len(started) == 1
    clock["t"] = 100
    notifier.tick()
    assert len(started) == 1, "still running"

    started[0].status = 75  # LDAP down
    notifier.tick()
    assert len(started) == 1
    clock["t"] = 100 + worker.Notifier.BACK_OFF
    notifier.tick()
    assert len(started) == 2

    started[1].status = 0
    due["value"] = False
    clock["t"] += worker.Notifier.CHECK_EVERY
    notifier.tick()
    assert len(started) == 2, "nothing due"


def test_the_sender_reports_an_ldap_outage_to_the_worker(app, db, rig, directory, monkeypatch):
    import run_notifications
    monkeypatch.setattr(run_notifications, "create_app", lambda: app)
    maintenance(db, rig["tycho"])
    directory["down"] = True
    assert run_notifications.main() == run_notifications.EX_TEMPFAIL
    directory["down"] = False
    app.config.update(SMTP_SERVER=None, SENDER_EMAIL=None)
    assert run_notifications.main() == 0


# --- group notifications ---------------------------------------------------------

def test_a_group_notification_reaches_the_groups_members_only(app, db, rig, directory, make_group, add_member):
    students = make_group(name="students")
    staff = make_group(name="staff")
    add_member(students, "ldap:alice")
    add_member(students, rig["carol"])
    add_member(staff, "ldap:dave")
    db.session.add(NotificationSettings(user_uid="ldap:alice", topic_maintenance=False, topic_expiry=False,
                                        topic_image=False, topic_dataset=False))
    notification = Notification(kind="group", status="scheduled", subject="Hello {group}",
                                body="Hi {name}\n{containers}")
    notification.params_dict = {"group_ids": [students.id]}
    db.session.add(notification)
    db.session.commit()

    found = audience.recipients(notification)
    assert [r.username for r in found] == ["alice", "carol"]
    assert len(found[0].containers) == 2, "their containers can still be listed"
    assert found[0].channels() == [("email", "alice@uni.example")], "topics don't apply"


def test_a_group_message_says_which_group(app, db, rig, directory, mail, make_group, add_member):
    students = make_group(name="students")
    add_member(students, "ldap:alice")
    notification = Notification(kind="group", status="scheduled", subject="Hello {group}", body="Hi {name}")
    notification.params_dict = {"group_ids": [students.id]}
    db.session.add(notification)
    db.session.commit()
    dispatch.run_once(NOW)
    [message] = mail.messages
    assert message["Subject"] == "[WhaP] Hello students"
    assert "You get this because you are a member of the WhaP group students." in \
        message.get_body(("plain",)).get_content()
