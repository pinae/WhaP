from playwright.sync_api import Page, expect


class SettingsPage:
    """/settings, reached from the gear in the header: where and about what WhaP notifies."""

    def __init__(self, page: Page):
        self.page = page
        self.email_switch = page.get_by_test_id("settings-email-switch")
        self.test_button = page.get_by_test_id("settings-test")
        self.risk_dialog = page.get_by_test_id("risk-dialog")
        self.off_banner = page.get_by_test_id("notifications-off-banner")

    @classmethod
    def from_header(cls, page: Page):
        page.get_by_test_id("header-settings").click()
        settings = cls(page)
        expect(settings.email_switch).to_be_visible()
        return settings

    def topic(self, name):
        return self.page.get_by_test_id(f"settings-topic-{name}")

    def send_test(self):
        """Send a test message; returns the result lines shown."""
        self.test_button.click()
        results = self.page.get_by_test_id("settings-test-result")
        expect(results.first).to_be_visible()
        return results.all_inner_texts()
