from playwright.sync_api import Page, expect


class AdminNotifications:
    """The Admin panel's Notifications tab: the list, the composer, the report."""

    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.goto("/admin?tab=notifications")
        expect(self.page.get_by_test_id("notif-new")).to_be_visible()
        return self

    def compose(self):
        self.page.get_by_test_id("notif-new").click()
        return Composer(self.page)


class Composer:
    def __init__(self, page: Page):
        self.page = page
        self.count = page.get_by_test_id("audience-count")
        self.preview = page.get_by_test_id("preview-email")

    def maintenance(self, server, start, end, subject):
        """Fill in a maintenance notice for ``server``; times as 'YYYY-MM-DDTHH:MM'."""
        self.page.get_by_test_id("composer-kind-maintenance").click()
        self.page.get_by_test_id("composer-servers").click()
        self.page.get_by_test_id(f"composer-server-{server}").click()
        self.page.keyboard.press("Escape")
        self.page.get_by_test_id("composer-start").fill(start)
        self.page.get_by_test_id("composer-end").fill(end)
        self.page.get_by_test_id("composer-subject").fill(subject)
        return self

    def when(self, choice):
        """Choose when to send: 'now', 'at', or for maintenance 'day_before'."""
        self.page.get_by_test_id("composer-schedule").click()
        self.page.get_by_test_id(f"composer-when-{choice}").click()
        expect(self.page.get_by_role("listbox")).to_be_hidden()
        return self

    def show_recipients(self):
        self.page.get_by_test_id("audience-show-all").click()
        dialog = self.page.get_by_test_id("audience-dialog")
        expect(dialog).to_be_visible()
        return dialog

    def send(self):
        """Review and send, confirm; returns the message the list then shows."""
        review = self.page.get_by_test_id("composer-review")
        expect(review).to_be_enabled()
        review.click()
        dialog = self.page.get_by_test_id("confirm-dialog")
        expect(dialog).to_be_visible()
        text = dialog.inner_text()
        dialog.get_by_test_id("confirm-send").click()
        expect(self.page.get_by_test_id("notif-message")).to_be_visible()
        return text
