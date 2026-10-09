from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from ..services import permissions_service
from ..models import ComputeServer
from ..config import roles_dirs
from .. import db
import os

perm_bp = Blueprint('permissions', __name__)


# -- Helper for getting the list of available images ---
def _get_all_system_images(app):
    """Helper function to read all available 'worker_' images from the roles path."""
    roles_path = app.config.get('ANSIBLE_ROLES_PATH')
    if not roles_path:
        app.logger.error("ANSIBLE_ROLES_PATH is not configured.")
        return None, "Image source (Ansible roles path) is not configured on the server."

    # Colon-separated, searched in order as Ansible does: a role in an earlier
    # directory hides one of the same name in a later one.
    directories = roles_dirs(roles_path)
    if not directories:
        app.logger.error(f"Configured ANSIBLE_ROLES_PATH '{roles_path}' names no existing directory.")
        return None, "Image source (Ansible roles path) is invalid on the server."

    images = []
    seen = set()
    try:
        for directory in directories:
            for item_name in os.listdir(directory):
                item_path = os.path.join(directory, item_name)
                if os.path.isdir(item_path) and item_name.startswith('worker_') and item_name not in seen:
                    seen.add(item_name)
                    display_name = item_name.replace('worker_', '', 1)
                    images.append({'id': item_name, 'name': display_name})
        images.sort(key=lambda x: x['name'])

        presorted_image_names = ["synced_ubuntu2404_ssh",
                                 "local_ubuntu2404_ssh",
                                 "synced_ubuntu2504_ssh",
                                 "local_ubuntu2504_ssh"]
        reordered_image_list = []
        for name in presorted_image_names:
            for image in images:
                if image['name'] == name and image not in reordered_image_list:
                    reordered_image_list.append(image)
        for image in images:
            if image not in reordered_image_list:
                reordered_image_list.append(image)

        return reordered_image_list, None
    except OSError as e:
        app.logger.error(f"Error reading Ansible roles directory '{roles_path}': {e}")
        return None, "Error reading image source on the server."


@perm_bp.route('/permissions/my-permissions', methods=['GET'])
@login_required
def get_my_permissions():
    """Gets the current user's aggregated permissions from all their groups."""
    try:
        user_id = current_user.get_id()
        permissions = permissions_service.get_user_permissions(user_id)
        return jsonify(permissions), 200
    except Exception as e:
        current_app.logger.error(f"Failed to get permissions for user {current_user.get_id()}: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve user permissions"), 500


@perm_bp.route('/permissions/my-available-images', methods=['GET'])
@login_required
def get_my_available_images():
    """
    Gets the list of images the current user has permission to grant,
    based on their aggregated group permissions.
    """
    try:
        # 1. Get user's permissions
        user_id = current_user.get_id()
        permissions = permissions_service.get_user_permissions(user_id)
        user_image_whitelist = permissions.get('image_whitelist', [])

        # 2. Get all system images
        all_images, error_msg = _get_all_system_images(current_app)
        if error_msg:
            return jsonify(message=error_msg), 500

        # 3. Filter based on permissions
        if '*' in user_image_whitelist:  # Admin or universal access
            return jsonify(all_images), 200
        else:
            # The user_image_whitelist is a list of role names (e.g., 'worker_pytorch')
            allowed_image_ids = set(user_image_whitelist)
            available_to_user = [
                image for image in all_images if image['id'] in allowed_image_ids
            ]
            return jsonify(available_to_user), 200

    except Exception as e:
        current_app.logger.error(f"Failed to get available images for user {current_user.get_id()}: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve user's available images"), 500


@perm_bp.route('/permissions/my-available-servers', methods=['GET'])
@login_required
def get_my_available_servers():
    """
    Gets the list of compute servers the current user has permission to use,
    based on their aggregated group permissions.
    """
    try:
        # 1. Get user's permissions
        user_id = current_user.get_id()
        permissions = permissions_service.get_user_permissions(user_id)
        user_server_ids = permissions.get('accessible_server_ids', [])

        # 2. Query servers based on permissions
        if '*' in user_server_ids:  # Admin or universal access
            servers = db.session.scalars(db.select(ComputeServer).order_by(ComputeServer.hostname)).all()
        else:
            if not user_server_ids:  # No permissions, return empty list
                return jsonify([]), 200

            servers = db.session.scalars(
                db.select(ComputeServer)
                .filter(ComputeServer.id.in_(user_server_ids))
                .order_by(ComputeServer.hostname)
            ).all()

        server_dicts = []
        cpu_limits = permissions.get('cpu_limits', {})
        for s in servers:
            s_dict = s.to_dict()
            # Inject the user specific CPU limit and usable GPUs. gpu_count
            # stays the number installed: the form shows every GPU and greys
            # out the ones not in allowed_gpus.
            s_dict['cpu_limit'] = cpu_limits.get(s.id)
            s_dict['allowed_gpus'] = permissions_service.allowed_gpus(permissions, s)
            server_dicts.append(s_dict)

        return jsonify(server_dicts), 200

    except Exception as e:
        current_app.logger.error(
            f"Failed to get available servers for user {current_user.get_id()}: {e}",
            exc_info=True)
        return jsonify(message="Failed to retrieve user's available servers"), 500


# --- Image Route (Read Only) ---
@perm_bp.route('/images', methods=['GET'])
@login_required
def get_images():
    """Dynamically lists ALL Ansible roles starting with 'worker_' from the configured roles path."""
    try:
        all_images, error_msg = _get_all_system_images(current_app)
        if error_msg:
            return jsonify({"message": error_msg}), 500
        return jsonify(all_images), 200
    except Exception as e:
        current_app.logger.error(f"Unexpected error listing images: {e}", exc_info=True)
        return jsonify({"message": "An unexpected error occurred while listing images."}), 500
