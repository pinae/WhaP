"""Waiting on a container's lifecycle, shared by the container tests."""
import time

from pages.user_panel import ContainerCard


def wait_until_settled(card, timeout, while_busy=None):
    """Wait while the card shows an Ansible job in flight; return the status it settles on.

    ``while_busy`` is called on every poll, for tests that watch the job as it runs.
    """
    deadline = time.monotonic() + timeout
    while card.status in ContainerCard.BUSY and time.monotonic() < deadline:
        if while_busy:
            while_busy()
        card.page.wait_for_timeout(250)
    return card.status


def delete_container(page, container_id, timeout):
    """Delete a container through the API unless it is already gone, and wait until it is.

    For teardown: frees the address and GPU for whatever runs next, also when
    the test that would have deleted it through the UI never got there.
    """
    path = f"/api/containers/{container_id}"
    if page.request.get(path).status == 404:
        return
    page.request.delete(path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and page.request.get(path).status != 404:
        time.sleep(5)


def tail(text, lines=40):
    return "\n".join(text.splitlines()[-lines:])
