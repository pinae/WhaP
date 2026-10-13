"""Notifications, end to end: a user's settings, an admin's maintenance notice and
an expiry reminder, as mail that really leaves the worker.

Every mail on the rig lands in Mailpit ([mail] api in rig.toml), whose API the
tests read. No container is started: the notices only need WhaP to believe
alice has one, so the admin adds a container record for her, and removes it
at the end.

Needs [users.admin] in rig.toml: a local admin the session's seed creates.
"""
import re
from datetime import datetime, timedelta, UTC
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from mail import Mailbox
from pages import AdminNotifications, SettingsPage, UserPanel


@pytest.fixture(scope="module")
def mailbox(rig):
    box = Mailbox(rig.mail_api)
    box.clear()
    return box


@pytest.fixture(scope="module")
def admin_required(rig):
    if "admin" not in rig.users:
        pytest.skip("rig.toml has no [users.admin]; see rig.example.toml")


@pytest.fixture(scope="module")
def api(playwright, rig, admin_required):
    """api("alice") / api("admin"): signed-in API sessions, for setting up what the UI tests look at."""
    sessions = {}

    def _for(who):
        if who not in sessions:
            context = playwright.request.new_context(
                base_url=rig.url, ignore_https_errors=bool(rig.browser.get("ignore_https_errors")))
            user = rig.users[who]
            response = context.post("/auth/login", data={"username": user.uid, "password": user.password})
            assert response.ok, f"{who} could not sign in: {response.text()}"
            sessions[who] = context
        return sessions[who]

    yield _for
    for context in sessions.values():
        context.dispose()


@pytest.fixture(scope="module")
def alices_container(api, rig, run_id):
    """A container record for alice on the compute server, in a project of hers. Record only."""
    alice, admin = api("alice"), api("admin")
    project = alice.post("/api/projects", data={"name": f"notify-{run_id}", "shares": []})
    assert project.ok, project.text()
    servers = admin.get("/api/servers").json()
    server = next((s for s in servers if s["hostname"] == rig.container.server), servers[0])
    created = admin.post("/api/admin/containers", data={
        "user_identifier": rig.users["alice"].prefixed, "project_id": project.json()["id"],
        "compute_server_id": server["id"], "image_name": rig.container.image, "status": "RUNNING", "gpus": "0"})
    assert created.ok, created.text()
    container = {**created.json(), "project": project.json()["name"], "server": server["hostname"]}
    yield container
    admin.delete(f"/api/admin/containers/{container['id']}")
    alice.delete(f"/api/projects/{project.json()['id']}")


def alices_address(rig):
    return f"{rig.users['alice'].uid}@whap.test"  # the e2e directory's mail attribute


# --- a user's settings ---------------------------------------------------------------

def test_a_user_finds_where_they_are_notified(login, rig):
    settings = SettingsPage.from_header(login("alice").page)
    expect(settings.page.get_by_text(alices_address(rig))).to_be_visible()
    expect(settings.email_switch).to_be_checked()
    for topic in ("maintenance", "expiry", "image", "dataset"):
        expect(settings.topic(topic)).to_be_checked()


def test_the_test_message_arrives(login, rig, mailbox):
    settings = SettingsPage.from_header(login("alice").page)
    assert settings.send_test() == [f"Sent to {alices_address(rig)}. Check that it arrived."]
    message = mailbox.wait_for(alices_address(rig), "Test notification", timeout=30)
    assert message["Subject"] == "[WhaP] Test notification"
    assert "notifications reach you here" in message["Text"]


def test_turning_everything_off_asks_first(login):
    settings = SettingsPage.from_header(login("alice").page)
    settings.email_switch.click()
    expect(settings.risk_dialog).to_be_visible()
    expect(settings.risk_dialog.get_by_test_id("risk-confirm")).to_be_disabled()
    settings.risk_dialog.get_by_test_id("risk-keep").click()
    expect(settings.risk_dialog).to_be_hidden()
    settings.page.reload()
    expect(settings.email_switch).to_be_checked()


# --- an admin's maintenance notice ------------------------------------------------------

def test_an_admin_announces_maintenance_and_alice_gets_it(login, rig, mailbox, alices_container, run_id):
    day = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    subject = f"{{server}} restarts on {{start}} ({run_id})"
    composer = AdminNotifications(login("admin").page).open().compose()
    composer.maintenance(alices_container["server"], f"{day}T08:00", f"{day}T09:00", subject).when("now")

    # Who it reaches, and what alice will read, before anything is sent.
    expect(composer.count).not_to_have_text("0")
    recipients = composer.show_recipients()
    expect(recipients.get_by_text(rig.users["alice"].uid, exact=True)).to_be_visible()
    expect(recipients.get_by_text(alices_container["project"], exact=False)).to_be_visible()
    recipients.get_by_role("button", name="Close").click()
    expect(composer.preview).to_contain_text(alices_container["project"])

    confirmation = composer.send()
    assert "Send “" in confirmation and "right away" in confirmation

    message = mailbox.wait_for(alices_address(rig), f"({run_id})")
    assert message["Subject"].startswith(f"[WhaP] {alices_container['server']} restarts on ")
    assert f"{alices_container['project']} ({rig.container.image}) on {alices_container['server']}" in message["Text"]
    assert "your containers are stopped before the restart" in message["Text"]
    assert f"You get this because you have containers on {alices_container['server']}." in message["Text"]


def test_the_report_shows_the_delivery(login, rig, run_id):
    page = AdminNotifications(login("admin").page).open().page
    page.get_by_test_id("notif-row").filter(has_text=f"({run_id})").click()
    delivery = page.get_by_test_id("report-delivery").filter(has_text=alices_address(rig))
    expect(delivery).to_have_attribute("data-status", "sent")


def test_alice_sees_the_maintenance_above_her_containers(login, alices_container, run_id):
    panel = login("alice")
    notice = panel.page.get_by_test_id("notice-maintenance").filter(has_text=f"({run_id})")
    expect(notice).to_contain_text(alices_container["project"])


# --- the automatic expiry reminder ---------------------------------------------------------

def test_an_expiring_project_is_reminded_and_the_link_offers_to_prolong(login, api, rig, mailbox, alices_container):
    ttl = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    changed = api("admin").put(f"/api/admin/containers/{alices_container['id']}", data={"ttl_date": ttl})
    assert changed.ok, changed.text()

    message = mailbox.wait_for(alices_address(rig), f"“{alices_container['project']}”")
    assert re.search(r"expires (in \d days|tomorrow)$", message["Subject"]), message["Subject"]
    home = f"/home/{rig.users['alice'].uid}/{alices_container['project']}"
    assert f"the local project directory {home} on {alices_container['server']} will be deleted" in message["Text"]
    link = re.search(r"https?://\S+prolong=\d+", message["Text"]).group(0)
    assert link.endswith(f"prolong={alices_container['id']}")

    # The link, opened by alice, asks whether to prolong. Not now: prolonging a
    # record without a container would send Ansible to the compute server.
    page = login("alice").page
    target = urlsplit(link)
    page.goto(f"{target.path}?{target.query}")
    dialog = page.get_by_test_id("prolong-dialog")
    expect(dialog).to_contain_text(f"Prolong “{alices_container['project']}” by four weeks?")
    dialog.get_by_role("button", name="Not now").click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_test_id("notice-expiry")).to_contain_text(alices_container["project"])


def test_the_admin_sees_the_reminder_was_sent(login, alices_container):
    page = AdminNotifications(login("admin").page).open().page
    sent = page.get_by_test_id("expiry-recent").filter(has_text=f"“{alices_container['project']}”")
    expect(sent).to_contain_text("1 delivered")
