from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from pathlib import Path
from ..models import Project, ProjectShare, LocalUser, Group
from ..user_management import LdapUserWrapper, LocalUserWrapper
from ..services.local_file_service import PROJECT_DIR_MODE
from ..services.task_queue_service import enqueue_rename_directory, enqueue_create_directory, enqueue_delete_directory
from .. import admin_required
from .. import db
import re

proj_bp = Blueprint('projects', __name__)


def _directory_owner(project):
    """Whom a project's directory belongs to: its owner, not the admin who
    created or reassigned it. A group project's directory goes to whoever acts
    on it, as when a member creates one."""
    if project.owner_local_user_id:
        return LocalUserWrapper(db.session.get(LocalUser, project.owner_local_user_id))
    if project.owner_uid:
        return LdapUserWrapper({'uid': project.owner_uid.removeprefix('ldap:')})
    return current_user


def _project_name_taken(name, owner_filter, exclude_id=None):
    """Return True if ``owner_filter`` already has a project called ``name``.

    ``owner_filter`` is a dict with exactly one of owner_uid /
    owner_local_user_id / owner_group_id (as produced by
    ``current_user.get_project_owner_dict()`` or built from admin input).
    Uniqueness is per-owner, so the check must be scoped to that owner rather
    than global -- and the resulting 409 never reveals another owner's projects.
    """
    query = db.select(Project).filter_by(name=name, **owner_filter)
    if exclude_id is not None:
        query = query.filter(Project.id != exclude_id)
    return db.session.scalar(query) is not None


def _is_owner(project):
    """True if the current user owns ``project`` directly (not via a group or share)."""
    owner = current_user.get_project_owner_dict()
    return bool((project.owner_local_user_id and project.owner_local_user_id == owner.get('owner_local_user_id'))
                or (project.owner_uid and project.owner_uid == owner.get('owner_uid')))


def get_project_fs_path(project: Project, project_name_override: str = None) -> Path:
    """
    Constructs the full filesystem path for a project.

    :param project: The Project model instance.
    :param project_name_override: Optional string to use instead of project.name
                                  (useful for rename operations before/after DB commit).
    :return: Path object (e.g., /var/whap/projects/john_doe/my_project)
    """
    storage_root = Path(current_app.config['PROJECT_STORAGE_DIR'])
    owner_dir = project.owner_dir_name
    # Use the override if provided (for renaming), otherwise the current model name
    p_name = project_name_override if project_name_override else project.name
    return storage_root / owner_dir / p_name


@proj_bp.route('/projects', methods=['GET'])
@login_required
def get_projects():
    owner_filter_data = current_user.get_project_owner_dict()
    owner_filter = {k: v for k, v in owner_filter_data.items() if v is not None}
    user_projects = Project.query.filter_by(**owner_filter).order_by(Project.name).all()
    return jsonify([p.to_dict() for p in user_projects]), 200


@proj_bp.route('/projects/<int:project_id>', methods=['GET'])
@login_required
def get_project_details(project_id):
    """A project with its share list, for its owner to edit. Owner-only like
    update and delete -- admins use the /admin/projects endpoints. Anyone else
    gets 404, so the endpoint doesn't confirm which ids exist."""
    project = db.get_or_404(Project, project_id)
    if not _is_owner(project):
        return jsonify(message="Project not found or access denied"), 404
    info = project.to_dict()
    info['shares'] = [s.to_dict() for s in project.shares.all()]
    return jsonify(info), 200


@proj_bp.route('/projects/<int:project_id>', methods=['PUT'])
@login_required
def update_project(project_id):
    """
    Updates a project's name and shares. Only the owner can do this.
    """
    project = db.get_or_404(Project, project_id)
    data = request.get_json()

    if not _is_owner(project):
        return jsonify(message="Access denied: Only the project owner can make changes."), 403

    # Update project name
    # Store old name for potential rename operation
    old_name = project.name
    new_name = data.get('name')
    old_path = get_project_fs_path(project)

    if new_name and new_name.strip() != old_name:
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$', new_name.strip()):
            return jsonify({"message": "Project name must start with a letter/number and contain only letters, numbers, underscores, dashes, and dots."}), 400

        if _project_name_taken(new_name.strip(), current_user.get_project_owner_dict(), exclude_id=project_id):
            return jsonify({"message": f"Project name '{new_name}' already exists"}), 409
        project.name = new_name.strip()
        new_path = get_project_fs_path(project)

        # Enqueue a job to rename the directory on the filesystem
        try:
            enqueue_rename_directory(old_path, new_path, current_user)
            current_app.logger.info(
                f"Enqueued rename job for project {project.id} from '{old_name}' to '{project.name}'.")
        except Exception as e:
            current_app.logger.error(f"Failed to enqueue rename job for project {project.id}: {e}", exc_info=True)
            # We don't fail the request, just log the error.

    # Update shares
    if 'shares' in data:  # Check for presence of the key
        # Delete-then-add strategy for shares
        ProjectShare.query.filter_by(project_id=project_id).delete()
        shares_data = data.get('shares', [])
        for share_item in shares_data:
            new_share = ProjectShare(
                project_id=project_id,
                user_uid=share_item['user_uid'],
                is_writable=share_item.get('is_writable', False)
            )
            db.session.add(new_share)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {current_user.get_id()} failed to update project {project_id}: {e}",
                                 exc_info=True)
        return jsonify({"message": "Failed to update project"}), 500

    # Directories of projects created before PROJECT_DIR_MODE are 0755, so
    # sharing one read-write would not let anyone else write. Re-apply the
    # mode (create_directory is idempotent). Not for group projects, whose
    # directory create_directory would hand to whoever made the change.
    if project.owner_group_id is None and project.shares.filter_by(is_writable=True).count():
        try:
            enqueue_create_directory(get_project_fs_path(project), current_user, mode=PROJECT_DIR_MODE)
        except Exception as e:
            current_app.logger.error(f"Failed to enqueue mode fix for project {project.id}: {e}", exc_info=True)

    try:
        project_data = project.to_dict()
        project_data['shares'] = [share.to_dict() for share in project.shares]
        return jsonify(project_data), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {current_user.get_id()} failed to update project {project_id}: {e}",
                                 exc_info=True)
        return jsonify({"message": "Failed to update project"}), 500


@proj_bp.route('/projects', methods=['POST'])
@login_required
def create_project():
    data = request.get_json()
    project_name = data.get('name')
    if not project_name:
        return jsonify({"message": "Project name is required"}), 400
    owner_data = current_user.get_project_owner_dict()
    if _project_name_taken(project_name, owner_data):
        return jsonify({"message": f"Project name '{project_name}' already exists"}), 409  # Conflict

    # Basic validation for project name (e.g., prevent slashes, weird chars)
    # Allow letters, numbers, underscore, hyphen, dots. Must start with alphanumeric.
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$', project_name):
        return jsonify({"message": "Project name must start with a letter/number and contain only letters, numbers, underscores, dashes, and dots."}), 400

    try:
        new_project = Project(name=project_name, **owner_data)
        db.session.add(new_project)
        db.session.commit()  # Commit to save to DB first

        if 'shares' in data:  # Check for presence of the key
            shares_data = data.get('shares', [])
            for share_item in shares_data:
                new_share = ProjectShare(
                    project_id=new_project.id,
                    user_uid=share_item['user_uid'],
                    is_writable=share_item.get('is_writable', False)
                )
                db.session.add(new_share)

        current_app.logger.info(f"User {current_user.get_id()} created project '{project_name}' (ID: {new_project.id})")

        # --- Enqueue a file operation job to create the directory ---
        try:
            project_path = get_project_fs_path(new_project)
            enqueue_create_directory(project_path, current_user, mode=PROJECT_DIR_MODE)
            current_app.logger.info(
                f"User {current_user.get_id()} created project '{project_name}' and enqueued directory creation job.")
        except Exception as file_op_err:
            current_app.logger.error(f"Failed to enqueue directory creation for project {project_name}: {file_op_err}",
                                     exc_info=True)

        return jsonify(new_project.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating project for user {current_user.get_id()}: {e}", exc_info=True)
        return jsonify({"message": "Failed to create project"}), 500


@proj_bp.route('/projects/<int:project_id>', methods=['DELETE'])
@login_required
def delete_project(project_id):
    """Allows a user to delete a project they own."""
    project = db.get_or_404(Project, project_id)

    if not _is_owner(project):
        return jsonify(message="Access denied: Only the project owner can delete this project."), 403

    # Safety check: Prevent deletion if containers are associated
    if project.containers.first():
        return jsonify(
            {"message": "Cannot delete project: It still has active containers. Please delete them first."}), 409

    try:
        project_name_for_log = project.name
        # Enqueue a job to delete the project's directory from storage
        project_path = get_project_fs_path(project)
        enqueue_delete_directory(project_path)
        current_app.logger.info(
            f"User {current_user.get_id()} enqueued directory deletion for project '{project_name_for_log}'.")

        db.session.delete(project)
        db.session.commit()
        current_app.logger.info(
            f"User {current_user.get_id()} deleted project ID {project_id} ('{project_name_for_log}').")
        return '', 204  # No Content
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {current_user.get_id()} failed to delete project {project_id}: {e}",
                                 exc_info=True)
        return jsonify({"message": "Failed to delete project"}), 500


@proj_bp.route('/admin/projects', methods=['GET'])
@login_required
@admin_required
def admin_get_projects():
    """Admin endpoint to list ALL projects."""
    try:
        all_projects = Project.query.order_by(Project.name).all()
        # Use the extended to_dict or ensure owner info is clear
        return jsonify([p.to_dict() for p in all_projects]), 200
    except Exception as e:
        current_app.logger.error(f"Admin failed to get projects: {e}")
        return jsonify(message="Failed to retrieve projects"), 500


@proj_bp.route('/admin/projects', methods=['POST'])
@login_required
@admin_required
def admin_create_project():
    """Admin endpoint to create a project with a specific owner (user or group)."""
    data = request.get_json()
    project_name = data.get('name')
    owner_uid = data.get('owner_uid')
    owner_local_user_id = data.get('owner_local_user_id')
    owner_group_id = data.get('owner_group_id')

    if not project_name:
        return jsonify({"message": "Project name is required"}), 400

    # Ensure exactly one owner type is provided
    owner_count = sum(1 for v in [owner_uid, owner_local_user_id, owner_group_id] if v)
    if owner_count != 1:
        return jsonify({"message": "Exactly one owner (LDAP, Local, or Group) must be specified"}), 400

    admin_owner_filter = {
        'owner_uid': owner_uid,
        'owner_local_user_id': owner_local_user_id,
        'owner_group_id': owner_group_id,
    }
    if _project_name_taken(project_name, admin_owner_filter):
        return jsonify({"message": f"Project name '{project_name}' already exists"}), 409

    if owner_local_user_id and not db.session.get(LocalUser, owner_local_user_id):
        return jsonify({"message": "Selected local user does not exist"}), 404
    if owner_group_id and not db.session.get(Group, owner_group_id):
        return jsonify({"message": "Selected group does not exist"}), 404

    try:
        new_project = Project(
            name=project_name,
            owner_uid=owner_uid,
            owner_local_user_id=owner_local_user_id,
            owner_group_id=owner_group_id
        )
        db.session.add(new_project)
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} created project '{project_name}'.")

        # --- Enqueue a file operation job to create the directory ---
        try:
            project_path = get_project_fs_path(new_project)
            enqueue_create_directory(project_path, _directory_owner(new_project), mode=PROJECT_DIR_MODE)
            current_app.logger.info(
                f"User {current_user.get_id()} created project '{project_name}' and enqueued directory creation job.")
        except Exception as file_op_err:
            current_app.logger.error(f"Failed to enqueue directory creation for project {project_name}: {file_op_err}",
                                     exc_info=True)

        return jsonify(new_project.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to create project '{project_name}': {e}", exc_info=True)
        return jsonify({"message": "Failed to create project"}), 500


@proj_bp.route('/admin/projects/<int:project_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_project(project_id):
    """Admin endpoint to update a project's name or owner."""
    project = db.get_or_404(Project, project_id)
    data = request.get_json()
    new_name = data.get('name')

    old_path = get_project_fs_path(project)

    # Owner reassignment is independent of renaming: apply it whenever owner
    # fields are present, even if no new name was supplied.
    if any(k in data for k in ['owner_uid', 'owner_local_user_id', 'owner_group_id']):
        owner_uid = data.get('owner_uid')
        owner_local_user_id = data.get('owner_local_user_id')
        owner_group_id = data.get('owner_group_id')

        owner_count = sum(1 for v in [owner_uid, owner_local_user_id, owner_group_id] if v)
        if owner_count != 1:
            return jsonify({"message": "Exactly one owner (LDAP, Local, or Group) must be specified"}), 400

        if owner_local_user_id and not db.session.get(LocalUser, owner_local_user_id):
            return jsonify({"message": "Selected local user does not exist"}), 404
        if owner_group_id and not db.session.get(Group, owner_group_id):
            return jsonify({"message": "Selected group does not exist"}), 404

        project.owner_uid = owner_uid
        project.owner_local_user_id = owner_local_user_id
        project.owner_group_id = owner_group_id
        db.session.flush()

    if new_name:
        # Uniqueness is per (effective) owner, so check against the project's
        # current owner (which may have just been reassigned above).
        effective_owner_filter = {
            'owner_uid': project.owner_uid,
            'owner_local_user_id': project.owner_local_user_id,
            'owner_group_id': project.owner_group_id,
        }
        if _project_name_taken(new_name, effective_owner_filter, exclude_id=project_id):
            return jsonify({"message": f"Project name '{new_name}' already exists"}), 409
        project.name = new_name

    new_path = get_project_fs_path(project)
    if old_path != new_path:
        try:
            enqueue_rename_directory(old_path, new_path, _directory_owner(project))
            current_app.logger.info(f"Admin renamed project path: {old_path} -> {new_path}")
        except Exception as file_op_err:
            current_app.logger.error(f"Failed to enqueue rename: {file_op_err}", exc_info=True)

    try:
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} updated project ID {project_id}.")
        return jsonify(project.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to update project {project_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to update project"}), 500


@proj_bp.route('/admin/projects/<int:project_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_project(project_id):
    """Admin endpoint to delete a project."""
    project = db.get_or_404(Project, project_id)

    if project.containers.first():
        return jsonify({"message": "Cannot delete project: It still has containers associated with it."}), 409

    try:
        project_name = project.name
        # Enqueue directory deletion before deleting the DB record
        project_path = get_project_fs_path(project)
        enqueue_delete_directory(project_path)
        current_app.logger.info(f"Enqueued directory deletion for project '{project_name}'.")

        db.session.delete(project)
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} deleted project ID {project_id} ('{project_name}').")
        return '', 204
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to delete project {project_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to delete project"}), 500
