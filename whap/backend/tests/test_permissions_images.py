"""Coverage for ``permissions._get_all_system_images`` -- the helper that turns
the ``worker_*`` Ansible role directories into the list of selectable images.

It's pure-ish (reads a directory, no DB / request context), so we point
``ANSIBLE_ROLES_PATH`` at a temporary directory and assert the discovery,
prefix-stripping, ordering, and error paths.
"""
import pytest

from app.routes.permissions import _get_all_system_images


def _make_roles(tmp_path, names):
    # Use a unique subdir name: the `app` fixture already creates a "roles"
    # directory under the same per-test tmp_path, so reusing that name collides
    # (FileExistsError) and could mix its contents into our assertions.
    roles = tmp_path / "image_roles"
    roles.mkdir()
    for name in names:
        (roles / name).mkdir()
    return str(roles)


def test_lists_only_worker_roles_and_strips_prefix(app, tmp_path):
    app.config["ANSIBLE_ROLES_PATH"] = _make_roles(
        tmp_path,
        ["worker_custom_role", "not_a_worker", "README", "worker_another"],
    )

    images, error = _get_all_system_images(app)

    assert error is None
    ids = {img["id"] for img in images}
    assert ids == {"worker_custom_role", "worker_another"}  # non-worker dirs excluded
    by_id = {img["id"]: img["name"] for img in images}
    assert by_id["worker_custom_role"] == "custom_role"  # 'worker_' stripped for display


def test_known_images_are_ordered_first(app, tmp_path):
    # Deliberately create them out of the "preferred" order.
    app.config["ANSIBLE_ROLES_PATH"] = _make_roles(
        tmp_path,
        [
            "worker_zzz_custom",
            "worker_local_ubuntu2404_ssh",
            "worker_synced_ubuntu2404_ssh",
        ],
    )

    images, error = _get_all_system_images(app)

    assert error is None
    ids = [img["id"] for img in images]
    # synced/local 2404 are pinned to the front in that order; extras follow.
    assert ids[0] == "worker_synced_ubuntu2404_ssh"
    assert ids[1] == "worker_local_ubuntu2404_ssh"
    assert "worker_zzz_custom" in ids[2:]


def test_unconfigured_roles_path_returns_error(app):
    app.config["ANSIBLE_ROLES_PATH"] = None

    images, error = _get_all_system_images(app)

    assert images is None
    assert error  # human-readable message, not an exception


def test_nonexistent_roles_path_returns_error(app, tmp_path):
    app.config["ANSIBLE_ROLES_PATH"] = str(tmp_path / "definitely_missing")

    images, error = _get_all_system_images(app)

    assert images is None
    assert error
