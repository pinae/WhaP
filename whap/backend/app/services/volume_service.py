"""Authoritative computation of which host paths a user is allowed to bind-mount.

Because users hold root inside their containers, a bind mount whose ``host_path``
was never granted to them is a host / cross-tenant compromise. This module is the
single source of truth for the allowed set, used both by the read-only
``/shared-volumes`` endpoint (which lists the options) and by container creation
(which must *enforce* them). Keeping both on the same function means the list a
user sees and the list the server accepts can never drift apart.
"""
import os

from flask import current_app
from sqlalchemy.orm import selectinload

from .. import db
from ..models import Project, ProjectShare, GroupMembership


def _nfs_to_local(nfs_path, project_base, local_base, datasets_base, datasets_local_base):
    """Mirror of the path rewrite used when presenting volumes to the user."""
    if datasets_base and nfs_path.startswith(datasets_base):
        return nfs_path.replace(datasets_base, datasets_local_base, 1)
    if project_base and nfs_path.startswith(project_base):
        return nfs_path.replace(project_base, local_base, 1)
    return nfs_path


def get_allowed_volumes(user):
    """Return the volumes ``user`` may mount, keyed by host path.

    Shape: ``{host_path: {'name', 'host_path', 'local_path', 'is_writable'}}``.

    Sources (later, more-privileged entries win on write access):
      1. Global datasets under ``DATASETS_BASE_PATH`` (read-only).
      2. The user's own projects (writable).
      3. Projects shared with the user directly or via a group (writable iff the
         share grants it).
    """
    user_id = user.get_id()
    project_base = current_app.config.get('PROJECT_STORAGE_DIR')
    local_base = current_app.config.get('LOCAL_BASE_PATH')
    datasets_base = current_app.config.get('DATASETS_BASE_PATH')
    datasets_local_base = current_app.config.get('DATASETS_LOCAL_BASE_PATH')

    def local_path(p):
        return _nfs_to_local(p, project_base, local_base, datasets_base, datasets_local_base)

    volumes = {}

    # 1. Global datasets (read-only).
    if datasets_base and os.path.isdir(datasets_base):
        try:
            for item in os.listdir(datasets_base):
                host_path = os.path.join(datasets_base, item)
                if os.path.isdir(host_path):
                    volumes[host_path] = {
                        'name': f"Dataset: {item}",
                        'host_path': host_path,
                        'local_path': local_path(host_path),
                        'is_writable': False,
                    }
        except OSError as e:
            current_app.logger.error(f"Could not read DATASETS directory '{datasets_base}': {e}")

    # 2. The user's own projects (writable).
    owner_filter = user.get_project_owner_dict()
    own_projects = db.session.scalars(db.select(Project).filter_by(**owner_filter)).all()
    for project in own_projects:
        host_path = os.path.join(project_base, user.username, project.name)
        volumes[host_path] = {
            'name': f"My Project: {project.name}",
            'host_path': host_path,
            'local_path': local_path(host_path),
            'is_writable': True,
        }

    # 3. Projects shared with the user directly or via groups.
    memberships = db.session.scalars(db.select(GroupMembership).filter_by(user_uid=user_id)).all()
    share_uids = [user_id] + [f'group:{m.group_id}' for m in memberships]
    shares = db.session.scalars(
        db.select(ProjectShare)
        .options(selectinload(ProjectShare.project).selectinload(Project.local_owner))
        .filter(ProjectShare.user_uid.in_(share_uids))
    ).all()

    for share in shares:
        project = share.project
        owner_username = None
        if project.owner_local_user_id:
            owner_username = project.local_owner.username
        elif project.owner_uid:
            owner_username = project.owner_uid
        if not owner_username:
            continue

        host_path = os.path.join(project_base, owner_username, project.name)
        # A user's own project (already added, writable) is never downgraded.
        if host_path in volumes and volumes[host_path]['name'].startswith("My Project"):
            continue
        existing_writable = volumes.get(host_path, {}).get('is_writable', False)
        volumes[host_path] = {
            'name': f"Shared: {project.name}",
            'host_path': host_path,
            'local_path': local_path(host_path),
            'is_writable': existing_writable or share.is_writable,
        }

    return volumes


def validate_requested_volumes(user, requested):
    """Check client-supplied ``additional_volumes`` against the allowed set.

    ``requested`` is the list of ``{host_path, container_path, is_writable}``
    dicts from the create request. Returns ``(ok, message)``; ``message`` is
    ``None`` when everything is permitted.

    Enforcement rules:
      * ``host_path`` must be present (after realpath normalization) in the
        allowed set — this also defeats ``..`` traversal, since an escaping path
        resolves outside every allowed root.
      * A writable mount is only allowed where the granted entry is writable.
    """
    if not requested:
        return True, None

    allowed = get_allowed_volumes(user)
    # Normalize allowed keys once so comparison is symlink/relative-safe.
    allowed_by_real = {}
    for host_path, spec in allowed.items():
        allowed_by_real[os.path.realpath(host_path)] = spec

    for vol in requested:
        host_path = vol.get('host_path')
        container_path = vol.get('container_path')
        if not host_path or not container_path:
            return False, "Each additional volume needs a host_path and a container_path."

        real = os.path.realpath(host_path)
        spec = allowed_by_real.get(real)
        if spec is None:
            return False, f"You are not permitted to mount host path '{host_path}'."

        if vol.get('is_writable') and not spec['is_writable']:
            return False, f"You only have read-only access to '{host_path}'."

    return True, None
