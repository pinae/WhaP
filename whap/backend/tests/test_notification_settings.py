"""A user's notification settings (WP3): channels, topics, the risk acknowledgement,
connecting Matrix with a code, and the test message."""
import re
from datetime import timedelta

import pytest

from app.models import NotificationSettings
from app.routes import notification_settings as routes


@pytest.fixture
def carol(app, db, make_local_user, mail, homeserver, login_as):
    """A logged-in local user with an email address; email and Matrix configured."""
    user = make_local_user(username="carol")
    user.email = "carol@uni.example"
    db.session.commit()
    login_as(user)
    return user


def saved(db, user):
    return db.session.get(NotificationSettings, f"local:{user.id}")


def code_from(homeserver):
    return re.search(r"Your WhaP code: (\d{6})", homeserver.calls[-1]["json"]["body"]).group(1)


def connect(client, homeserver, matrix_id="@carol:uni.example"):
    assert client.post("/api/notification-settings/matrix", json={"matrix_id": matrix_id}).status_code == 200
    return client.post("/api/notification-settings/matrix/verify", json={"code": code_from(homeserver)})


# --- reading and switching ---------------------------------------------------

def test_a_new_user_gets_email_about_everything(client, carol):
    view = client.get("/api/notification-settings").get_json()
    assert view["email"] == {"enabled": True, "address": "carol@uni.example", "available": True}
    assert view["matrix"]["available"] and not view["matrix"]["enabled"]
    assert view["topics"] == {"maintenance": True, "expiry": True, "image": True, "dataset": True}
    assert view["reminder_days"] == [7, 1]
    assert view["reachable"] == ["email"] and view["protects_data"]


def test_switching_a_topic_off_is_saved(client, db, carol):
    resp = client.put("/api/notification-settings", json={"topics": {"image": False}})
    assert resp.status_code == 200
    assert resp.get_json()["topics"]["image"] is False
    assert saved(db, carol).topic_image is False


@pytest.mark.parametrize("body", [
    {"topics": {"newsletter": False}},
    {"topics": {"image": "no"}},
    {"email_enabled": "off"},
    {"matrix_enabled": True},  # nothing connected
    [],
])
def test_nonsense_is_refused(client, db, carol, body):
    assert client.put("/api/notification-settings", json=body).status_code == 400
    assert saved(db, carol) is None


@pytest.mark.parametrize("uid, domain, suggestion", [
    ("merkepkb", "ruhr-uni-bochum.de", "@merkepkb:ruhr-uni-bochum.de"),
    ("MerkePKB", "ruhr-uni-bochum.de", "@merkepkb:ruhr-uni-bochum.de"),  # Matrix IDs are lower case
    ("merkepkb", ":ruhr-uni-bochum.de", "@merkepkb:ruhr-uni-bochum.de"),
    ("merkepkb", "", None),
])
def test_ldap_users_get_their_university_matrix_id_filled_in(app, client, mail, homeserver, directory,
                                                              login_as, monkeypatch, uid, domain, suggestion):
    monkeypatch.setattr("app.user_management.ldap_service.get_ldap_user_details",
                        lambda uid: {"uid": uid, "uidNumber": "70001", "gidNumber": "70000"})
    app.config["MATRIX_USER_DOMAIN"] = domain
    login_as(f"ldap:{uid}")
    assert client.get("/api/notification-settings").get_json()["matrix"]["suggestion"] == suggestion


def test_local_users_get_no_matrix_id_filled_in(app, client, carol):
    app.config["MATRIX_USER_DOMAIN"] = "ruhr-uni-bochum.de"
    assert client.get("/api/notification-settings").get_json()["matrix"]["suggestion"] is None


# --- the risk acknowledgement ------------------------------------------------

def test_turning_off_the_only_channel_needs_an_acknowledgement(client, db, carol):
    refused = client.put("/api/notification-settings", json={"email_enabled": False})
    assert refused.status_code == 409
    assert refused.get_json()["needs_acknowledgement"] and refused.get_json()["all_off"]
    assert saved(db, carol) is None, "nothing was changed"

    accepted = client.put("/api/notification-settings", json={"email_enabled": False, "acknowledge_risk": True})
    assert accepted.status_code == 200
    assert not accepted.get_json()["protects_data"]
    assert saved(db, carol).all_off_acknowledged_at is not None


def test_turning_off_both_data_topics_needs_an_acknowledgement_but_one_does_not(client, carol):
    assert client.put("/api/notification-settings", json={"topics": {"maintenance": False}}).status_code == 200
    refused = client.put("/api/notification-settings", json={"topics": {"expiry": False}})
    assert refused.status_code == 409 and not refused.get_json()["all_off"]


def test_once_unprotected_further_changes_need_no_new_acknowledgement(client, db, carol):
    client.put("/api/notification-settings", json={"email_enabled": False, "acknowledge_risk": True})
    assert client.put("/api/notification-settings", json={"topics": {"image": False}}).status_code == 200


def test_turning_back_on_clears_the_acknowledgement(client, db, carol):
    client.put("/api/notification-settings", json={"email_enabled": False, "acknowledge_risk": True})
    view = client.put("/api/notification-settings", json={"email_enabled": True}).get_json()
    assert view["protects_data"] and view["risk_acknowledged_at"] is None
    assert saved(db, carol).all_off_acknowledged_at is None


def test_email_off_is_fine_while_matrix_reaches_the_user(client, carol, homeserver):
    connect(client, homeserver)
    resp = client.put("/api/notification-settings", json={"email_enabled": False})
    assert resp.status_code == 200 and resp.get_json()["reachable"] == ["matrix"]


def test_without_an_address_email_does_not_count(app, client, db, carol):
    carol.email = None
    db.session.commit()
    view = client.get("/api/notification-settings").get_json()
    assert view["reachable"] == [] and not view["protects_data"]


# --- connecting Matrix ---------------------------------------------------------

def test_the_bot_opens_a_chat_and_sends_a_code(client, db, carol, homeserver):
    resp = client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:uni.example"})
    assert resp.status_code == 200
    assert resp.get_json()["matrix"]["pending_id"] == "@carol:uni.example"
    create, send = homeserver.calls
    assert create["json"]["invite"] == ["@carol:uni.example"]
    assert "/rooms/%21new%3Ax/send/" in send["url"]
    settings = saved(db, carol)
    assert settings.matrix_id is None and settings.matrix_code_hash
    assert code_from(homeserver) not in settings.matrix_code_hash, "only a hash is stored"


def test_the_right_code_connects_the_account(client, db, carol, homeserver):
    view = connect(client, homeserver).get_json()
    assert view["matrix"]["id"] == "@carol:uni.example" and view["matrix"]["enabled"]
    assert view["matrix"]["pending_id"] is None
    assert view["reachable"] == ["email", "matrix"]
    assert saved(db, carol).matrix_room_id == "!new:x"


def test_wrong_codes_are_counted_and_end_the_attempt(client, db, carol, homeserver):
    client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:uni.example"})
    right = code_from(homeserver)
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(routes.CODE_MAX_ATTEMPTS - 1):
        assert "not the code" in client.post("/api/notification-settings/matrix/verify",
                                             json={"code": wrong}).get_json()["message"]
    last = client.post("/api/notification-settings/matrix/verify", json={"code": wrong})
    assert "Too many wrong codes" in last.get_json()["message"]
    after = client.post("/api/notification-settings/matrix/verify", json={"code": right})
    assert after.status_code == 400 and saved(db, carol).matrix_id is None


def test_an_expired_code_does_not_connect(client, db, carol, homeserver, monkeypatch):
    client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:uni.example"})
    later = routes._now() + routes.CODE_VALID_FOR + timedelta(seconds=1)
    monkeypatch.setattr(routes, "_now", lambda: later)
    resp = client.post("/api/notification-settings/matrix/verify", json={"code": code_from(homeserver)})
    assert resp.status_code == 400 and "expired" in resp.get_json()["message"]


def test_a_new_code_waits_a_minute_and_reuses_the_chat(client, carol, homeserver, monkeypatch):
    client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:uni.example"})
    again = client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:uni.example"})
    assert again.status_code == 429
    later = routes._now() + routes.CODE_RESEND_AFTER + timedelta(seconds=1)
    monkeypatch.setattr(routes, "_now", lambda: later)
    assert client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:uni.example"}).status_code == 200
    assert [c["method"] for c in homeserver.calls] == ["POST", "PUT", "PUT"], "no second chat"


@pytest.mark.parametrize("matrix_id", ["carol", "@carol", "carol:uni.example", "@ca rol:uni.example"])
def test_only_matrix_ids_are_accepted(client, carol, homeserver, matrix_id):
    assert client.post("/api/notification-settings/matrix", json={"matrix_id": matrix_id}).status_code == 400
    assert homeserver.calls == []


def test_a_refusing_homeserver_is_reported(client, db, carol, homeserver):
    from notification_fixtures import Reply
    homeserver.replies.append(Reply(403, {"errcode": "M_FORBIDDEN", "error": "user not found"}))
    resp = client.post("/api/notification-settings/matrix", json={"matrix_id": "@ghost:uni.example"})
    assert resp.status_code == 502 and "M_FORBIDDEN" in resp.get_json()["message"]
    assert saved(db, carol) is None


def test_without_a_bot_matrix_cannot_be_connected(app, client, carol, homeserver):
    app.config.update(MATRIX_HOMESERVER_URL="", MATRIX_ACCESS_TOKEN=None)
    assert client.get("/api/notification-settings").get_json()["matrix"]["available"] is False
    assert client.post("/api/notification-settings/matrix", json={"matrix_id": "@c:x.org"}).status_code == 400


def test_cancelling_forgets_the_code(client, db, carol, homeserver):
    client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:uni.example"})
    view = client.delete("/api/notification-settings/matrix/pending").get_json()
    assert view["matrix"]["pending_id"] is None and saved(db, carol).matrix_code_hash is None


def test_another_id_replaces_the_connected_one_only_once_verified(client, db, carol, homeserver):
    connect(client, homeserver)
    from notification_fixtures import Reply
    homeserver.replies.extend([Reply(200, {"room_id": "!second:x"}), Reply(200, {"event_id": "$e"})])
    client.post("/api/notification-settings/matrix", json={"matrix_id": "@carol:other.org"})
    assert saved(db, carol).matrix_id == "@carol:uni.example", "still the old one"

    view = client.post("/api/notification-settings/matrix/verify", json={"code": code_from(homeserver)}).get_json()
    assert view["matrix"]["id"] == "@carol:other.org"
    assert saved(db, carol).matrix_room_id == "!second:x"
    assert homeserver.calls[-1]["url"].endswith("/rooms/%21new%3Ax/leave"), "the old chat is left"


def test_disconnecting_leaves_the_chat(client, db, carol, homeserver):
    connect(client, homeserver)
    view = client.delete("/api/notification-settings/matrix").get_json()
    assert view["matrix"]["id"] is None and view["reachable"] == ["email"]
    assert homeserver.calls[-1]["url"].endswith("/rooms/%21new%3Ax/leave")


def test_disconnecting_the_last_channel_needs_an_acknowledgement(client, db, carol, homeserver):
    connect(client, homeserver)
    client.put("/api/notification-settings", json={"email_enabled": False})
    assert client.delete("/api/notification-settings/matrix").status_code == 409
    assert saved(db, carol).matrix_id == "@carol:uni.example"
    assert client.delete("/api/notification-settings/matrix", json={"acknowledge_risk": True}).status_code == 200


# --- test message ----------------------------------------------------------------

def test_the_test_message_goes_to_every_channel_that_reaches_the_user(client, carol, mail, homeserver):
    connect(client, homeserver)
    resp = client.post("/api/notification-settings/test")
    assert resp.get_json()["results"] == [
        {"channel": "email", "address": "carol@uni.example", "ok": True},
        {"channel": "matrix", "address": "@carol:uni.example", "ok": True},
    ]
    assert mail.messages[-1]["Subject"] == "[WhaP] Test notification"
    assert homeserver.calls[-1]["json"]["body"].startswith("Test notification")


def test_a_failing_test_message_says_why(app, client, carol):
    from notification_fixtures import free_port
    app.config["SMTP_PORT"] = str(free_port())
    [result] = client.post("/api/notification-settings/test").get_json()["results"]
    assert result["ok"] is False and "Could not connect" in result["error"]


def test_no_test_without_a_channel(client, carol):
    client.put("/api/notification-settings", json={"email_enabled": False, "acknowledge_risk": True})
    assert client.post("/api/notification-settings/test").status_code == 400


def test_settings_need_a_login(client):
    assert client.get("/api/notification-settings").status_code == 401
