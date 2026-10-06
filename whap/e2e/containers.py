"""Shared by the container tests: waiting on a container's lifecycle, and what every image must offer."""
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


# What users rely on in every image, each as a command that succeeds only if it works.
USER_TOOLS = {
    "tmux": "tmux -V",
    "nvtop": "nvtop --version",
    # pip proves ensurepip came along: without python3-venv, creating the venv fails right there.
    "venv": 'd=$(mktemp -d) && python3 -m venv "$d/v" && "$d/v/bin/pip" --version; s=$?; rm -rf "$d"; exit $s',
}

# Tools an image is known to lack, and why.
MISSING_TOOLS = {
    "worker_synced_nvidia_pytorch1906": {"nvtop": "its Ubuntu 18.04 base has no nvtop package"},
}


def broken_user_tools(sh, role):
    """Run the USER_TOOLS checks ``role`` should pass; return a report of those that fail, or ""."""
    exempt = MISSING_TOOLS.get(role, {})
    failed = {tool: sh.run(command) for tool, command in USER_TOOLS.items() if tool not in exempt}
    return "\n".join(f"--- {tool} ---\n{result}" for tool, result in failed.items() if result.exit_status != 0)
