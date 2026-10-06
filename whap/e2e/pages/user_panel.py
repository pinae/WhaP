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

    def _choose(self, select, option):
        """Pick an option from an MUI select the way a person does: open it, click."""
        dropdown = self.page.get_by_test_id(select)
        expect(dropdown).not_to_have_attribute("aria-disabled", "true")  # options still loading
        dropdown.click()
        self.page.get_by_test_id(option).click()
        expect(self.page.get_by_role("listbox")).to_be_hidden()

    def fill(self, *, project, image, ssh_key=None, password=None, server=None, gpus=(), volumes=()):
        """Fill in the form without submitting it.

        ``image`` is the role name (worker_...). ``server`` may be omitted when
        the user has exactly one, which the form pre-selects. ``volumes`` are
        labels as the volume list shows them, e.g. "Dataset: x (ro)"; each is
        mounted where the form suggests, recorded in ``self.mount_paths``.
        """
        self._choose("container-project-select", f"container-project-option-{project}")
        self._choose("container-image-select", f"container-image-option-{image}")
        if ssh_key:
            self._choose("container-sshkey-select", f"container-sshkey-option-{ssh_key}")
        if password:
            self.page.get_by_test_id("container-password").fill(password)
        if server:
            self._choose("container-server-select", f"container-server-option-{server}")
        for gpu in gpus:
            self.page.get_by_test_id(f"container-gpu-{gpu}").check()
        self.mount_paths = {label: self.add_volume(label) for label in volumes}
        return self

    def submit(self):
        self.page.get_by_test_id("container-submit").click()

    def start(self, *, project, image, **choices):
        """Fill in the form and press Start. Returns the new container's card."""
        self.fill(project=project, image=image, **choices).submit()
        # The panel switches to My Containers, where the new card appears.
        expect(self.page.get_by_test_id("tab-containers")).to_have_attribute("aria-selected", "true")
        return ContainerCard.newest(self.page, project=project, image=image)

    def error(self):
        """The error the form shows, waiting for it to appear."""
        alert = self.page.get_by_test_id("container-form-error")
        expect(alert).to_be_visible()
        return alert.inner_text().strip()

    def add_volume(self, label):
        """Mount a volume through "Add Volume"; return the container path the form suggests."""
        self._open_volume_list()
        option = self.page.get_by_role("listbox").get_by_role("option", name=label, exact=True)
        host_path = option.get_attribute("data-value")
        option.click()
        self.page.get_by_test_id("volume-add-confirm").click()
        return self.page.get_by_test_id(f"mounted-volume-path-{host_path}").input_value()

    def _open_volume_list(self):
        add = self.page.get_by_test_id("container-volume-add")
        expect(add).to_be_enabled()  # disabled until the list has loaded
        add.click()
        self.page.get_by_test_id("volume-select").click()

    def mountable_volumes(self):
        """Open "Add Volume" and return what it offers, e.g. ['Shared: x (ro)', ...]."""
        self._open_volume_list()
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


class ContainerCard:
    """One container on My Containers. Its state is read from the card's
    data-* attributes rather than from the text a person sees."""

    # Statuses while an Ansible job is in flight (ContainerDetail.js isJobRunning).
    BUSY = {"PENDING", "STARTING", "PAUSING", "STOPPING", "DELETING"}

    def __init__(self, page: Page, container_id):
        self.page = page
        self.id = str(container_id)
        self.locator = page.locator(f'[data-testid="container-card"][data-container-id="{self.id}"]')

    @classmethod
    def newest(cls, page, *, project, image):
        """The card of the most recently created container for project and image."""
        cards = page.locator(f'[data-testid="container-card"][data-project="{project}"][data-image="{image}"]')
        expect(cards.first).to_be_visible()
        ids = [int(card.get_attribute("data-container-id")) for card in cards.all()]
        return cls(page, max(ids))

    @property
    def status(self):
        return self.locator.get_attribute("data-status")

    @property
    def log(self):
        return self.locator.get_by_test_id("container-log")

    def live_lines(self):
        """Log lines that arrived over the socket since the card mounted; 0 if the pane is closed."""
        return int(self.log.get_attribute("data-live-lines") or 0) if self.log.count() else 0

    def log_text(self):
        if not self.log.count():
            self.locator.get_by_test_id("container-logs-toggle").click()
        return self.log.inner_text()

    def ip(self):
        return self.locator.get_by_test_id("container-ip").inner_text().strip()

    def ssh_command(self):
        return self.locator.get_by_test_id("container-ssh-command").inner_text().strip()

    def delete(self):
        self.locator.get_by_test_id("container-action-delete").click()
