from playwright.sync_api import Page, expect


class LoginPage:
    def __init__(self, page: Page):
        self.page = page
        self.username = page.get_by_test_id("login-username")
        self.password = page.get_by_test_id("login-password")
        self.submit = page.get_by_test_id("login-submit")
        self.error = page.get_by_test_id("login-error")

    def open(self):
        self.page.goto("/login")
        expect(self.username).to_be_visible()
        return self

    def attempt(self, uid, password):
        """Fill in the form and submit, without assuming it works."""
        self.username.fill(uid)
        self.password.fill(password)
        self.submit.click()

    def login(self, uid, password):
        """Sign in and wait for the user panel. Returns it."""
        from .user_panel import UserPanel
        self.attempt(uid, password)
        panel = UserPanel(self.page)
        expect(panel.username).to_have_text(uid)
        return panel
