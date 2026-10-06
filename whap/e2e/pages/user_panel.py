from playwright.sync_api import Page, expect


class UserPanel:
    """The /user page: the header, its tabs, and what each tab shows."""

    def __init__(self, page: Page):
        self.page = page
        self.username = page.get_by_test_id("header-username")
        self.logout_button = page.get_by_test_id("header-logout")

    def open(self):
        self.page.goto("/user")
        expect(self.username).to_be_visible()
        return self

    def logout(self):
        self.logout_button.click()
        expect(self.page.get_by_test_id("login-username")).to_be_visible()

    def tab(self, name):
        """Click a tab: statistics, containers, create, projects, groups, sshKeys."""
        self.page.get_by_test_id(f"tab-{name}").click()
        expect(self.page.get_by_test_id(f"tab-{name}")).to_have_attribute("aria-selected", "true")

    # --- My Projects -----------------------------------------------------------

    def projects(self):
        self.tab("projects")
        return Projects(self.page)

    # --- My SSH Keys -----------------------------------------------------------

    def ssh_keys(self):
        self.tab("sshKeys")
        return SSHKeys(self.page)

    # --- Create Container ------------------------------------------------------

    def create_container(self):
        self.tab("create")
        return CreateContainer(self.page)


class CreateContainer:
    PLACEHOLDER = "Select a folder to mount"

    def __init__(self, page: Page):
        self.page = page

    def mountable_volumes(self):
        """Open "Add Volume" and return what it offers, e.g. ['Shared: x (ro)', ...]."""
        add = self.page.get_by_test_id("container-volume-add")
        expect(add).to_be_enabled()  # disabled until the list has loaded
        add.click()
        self.page.get_by_test_id("volume-select").click()
        options = self.page.get_by_role("listbox").get_by_role("option")
        expect(options.first).to_be_visible()
        labels = [label.strip() for label in options.all_inner_texts()]
        self.page.keyboard.press("Escape")  # the list
        self.page.keyboard.press("Escape")  # the dialog
        return [label for label in labels if label != self.PLACEHOLDER]


class Projects:
    def __init__(self, page: Page):
        self.page = page

    def row(self, name):
        return self.page.get_by_test_id(f"project-row-{name}")

    def create(self, name):
        self.page.get_by_test_id("project-add").click()
        self.page.get_by_test_id("project-name-input").fill(name)
        self.page.get_by_test_id("project-modal-submit").click()
        expect(self.row(name)).to_be_visible()
        return self.row(name)

    def share(self, name, user_uid, writable=False):
        """Share a project with a user, found through the search box as a person would."""
        self.page.get_by_test_id(f"project-edit-{name}").click()
        search = self.page.get_by_test_id("member-search-input")
        search.fill(user_uid.split(":", 1)[1])
        self.page.get_by_test_id(f"member-add-{user_uid}").click()
        expect(self.page.get_by_test_id(f"member-row-{user_uid}")).to_be_visible()
        if writable:
            self.page.get_by_test_id(f"member-toggle-{user_uid}").check()
        self.page.get_by_test_id("project-modal-submit").click()
        expect(self.page.get_by_test_id("project-modal-submit")).to_be_hidden()

    def delete(self, name):
        self.page.get_by_test_id(f"project-delete-{name}").click()
        self.page.get_by_test_id("confirm-delete").click()
        expect(self.row(name)).to_be_hidden()


class SSHKeys:
    def __init__(self, page: Page):
        self.page = page

    def row(self, name):
        return self.page.get_by_test_id(f"sshkey-row-{name}")

    def add(self, name, public_key):
        self.page.get_by_test_id("sshkey-add").click()
        self.page.get_by_test_id("sshkey-name-input").fill(name)
        self.page.get_by_test_id("sshkey-public-key-input").fill(public_key)
        self.page.get_by_test_id("sshkey-modal-submit").click()
        expect(self.row(name)).to_be_visible()
        return self.row(name)

    def shown_public_key(self, name):
        """Expand a key and return the public key text the panel shows."""
        self.page.get_by_test_id(f"sshkey-show-{name}").click()
        shown = self.page.get_by_test_id("sshkey-list").locator("pre", has_text="ssh-")
        expect(shown).to_be_visible()
        return shown.inner_text().strip()
