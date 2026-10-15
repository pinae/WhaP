"""The images worker roles' containers run, and their tags.

The roles in SHARED_IMAGE_ROLES (compose_builder) have one image for all their
users: the entrypoint sets the user up when a container starts. Its tag is a
hash of the files it is built from, so a change to them is a new image, built
and pushed to the registry the first time a server needs it
(roles/common_tasks/tasks/shared_image.yml), and an image is never replaced
under the same name: what a test run builds can't change what production runs,
and the same role files anywhere give the same image.
"""
import hashlib
import os

from flask import current_app, has_app_context

from ..config import roles_dirs

# What shared_image.yml copies into the build directory, relative to the role.
BUILD_FILES = ("templates/Dockerfile.j2", "files/entrypoint.sh", "files/nopasswd")
TAG_LENGTH = 12


def role_dir(role_name, roles_path=None):
    """The role's directory, as Ansible finds it in ANSIBLE_ROLES_PATH, or None."""
    if roles_path is None:
        roles_path = current_app.config.get("ANSIBLE_ROLES_PATH") if has_app_context() else None
    for directory in roles_dirs(roles_path):
        candidate = os.path.join(directory, role_name)
        if os.path.isdir(candidate):
            return candidate
    return None


def image_tag(role_name, roles_path=None):
    """The first TAG_LENGTH hex digits of a SHA-256 over the role's build files.

    "latest" if the role can't be found here; Ansible will fail on it anyway.
    """
    directory = role_dir(role_name, roles_path)
    if directory is None:
        return "latest"
    digest = hashlib.sha256()
    for name in BUILD_FILES:
        path = os.path.join(directory, name)
        digest.update(name.encode() + b"\0")
        if os.path.exists(path):
            with open(path, "rb") as f:
                digest.update(f.read())
        digest.update(b"\0")
    return digest.hexdigest()[:TAG_LENGTH]
