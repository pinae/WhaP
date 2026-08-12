from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from ..models import UserSSHKey, ContainerInstance, LocalUser
from .. import admin_required
from .. import db

sshk_bp = Blueprint('sshkeys', __name__)


@sshk_bp.route('/sshkeys', methods=['GET'])
@login_required
def get_ssh_keys():
    # This assumes key.user_uid holds either LDAP uid or "local:<id>" string
    keys = UserSSHKey.query.filter_by(user_uid=current_user.get_id()).order_by(UserSSHKey.name).all()
    return jsonify([k.to_dict() for k in keys]), 200


@sshk_bp.route('/sshkeys', methods=['POST'])
@login_required
def add_ssh_key():
    data = request.get_json()
    name = data.get('name')
    public_key = data.get('public_key')
    # ... (validation) ...
    if not name or not public_key:  # Basic check
        return jsonify({"message": "Key name and public key string are required"}), 400
    if not public_key.startswith(('ssh-rsa', 'ssh-dss', 'ssh-ed25519', 'ecdsa-sha2-nistp')):
        return jsonify({"message": "Invalid public key format"}), 400

    # Use the prefixed ID as the owner identifier string for the key
    owner_id_str = current_user.get_id()
    existing_key = UserSSHKey.query.filter_by(user_uid=owner_id_str, name=name).first()
    if existing_key:
        return jsonify({"message": f"SSH Key with name '{name}' already exists for this user"}), 409

    try:
        new_key = UserSSHKey(user_uid=owner_id_str, name=name, public_key=public_key)
        db.session.add(new_key)
        db.session.commit()
        current_app.logger.info(f"Added SSH key '{name}' for user {owner_id_str}")
        return jsonify(new_key.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding SSH key for user {owner_id_str}: {e}")
        return jsonify({"message": "Failed to add SSH key"}), 500


@sshk_bp.route('/sshkeys/<int:key_id>', methods=['DELETE'])
@login_required
def delete_ssh_key(key_id):
    owner_id_str = current_user.get_id()
    key = UserSSHKey.query.filter_by(id=key_id, user_uid=owner_id_str).first_or_404()
    # ... (delete logic) ...
    try:
        db.session.delete(key)
        db.session.commit()
        current_app.logger.info(f"Deleted SSH key ID {key_id} ('{key.name}') for user {owner_id_str}")
        return jsonify({"message": "SSH Key deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting SSH key {key_id} for user {owner_id_str}: {e}")
        return jsonify({"message": "Failed to delete SSH key"}), 500


@sshk_bp.route('/admin/sshkeys', methods=['GET'])
@login_required
@admin_required
def admin_get_all_sshkeys():
    """Admin endpoint to list ALL SSH keys."""
    try:
        all_keys = UserSSHKey.query.order_by(UserSSHKey.user_uid, UserSSHKey.name).all()
        keys_list = []
        for k in all_keys:
            key_dict = k.to_dict()
            key_dict['user_uid'] = k.user_uid
            keys_list.append(key_dict)
        return jsonify(keys_list), 200
    except Exception as e:
        current_app.logger.error(f"Admin failed to get all ssh keys: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve all SSH keys"), 500


@sshk_bp.route('/admin/sshkeys', methods=['POST'])
@login_required
@admin_required
def admin_create_sshkey():
    """Admin endpoint to create an SSH key for any user."""
    data = request.get_json()
    name = data.get('name')
    public_key = data.get('public_key')
    user_identifier = data.get('user_identifier')

    if not all([name, public_key, user_identifier]):
        return jsonify({"message": "Name, public_key, and user_identifier are required"}), 400

    if UserSSHKey.query.filter_by(user_uid=user_identifier, name=name).first():
        return jsonify({"message": f"Key with name '{name}' already exists for owner '{user_identifier}'"}), 409

    try:
        user_type, user_id_str = user_identifier.split(':', 1)
        if user_type == 'local' and not LocalUser.query.get(int(user_id_str)):
            return jsonify({"message": f"Local user with ID {user_id_str} not found"}), 404

        new_key = UserSSHKey(user_uid=user_identifier, name=name, public_key=public_key)
        db.session.add(new_key)
        db.session.commit()

        key_dict = new_key.to_dict()
        key_dict['user_uid'] = new_key.user_uid
        return jsonify(key_dict), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to create SSH key: {e}", exc_info=True)
        return jsonify({"message": "Failed to create SSH key"}), 500


@sshk_bp.route('/admin/sshkeys/<int:key_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_sshkey(key_id):
    """Admin endpoint to update any SSH key."""
    key = UserSSHKey.query.get_or_404(key_id)
    data = request.get_json()
    new_name = data.get('name', key.name)
    new_user_identifier = data.get('user_identifier', key.user_uid)

    if new_name != key.name or new_user_identifier != key.user_uid:
        if UserSSHKey.query.filter(UserSSHKey.id != key_id, UserSSHKey.user_uid == new_user_identifier,
                                   UserSSHKey.name == new_name).first():
            return jsonify(
                {"message": f"Key with name '{new_name}' already exists for owner '{new_user_identifier}'"}), 409

    try:
        key.name = new_name
        key.user_uid = new_user_identifier
        if 'public_key' in data:
            key.public_key = data['public_key']

        db.session.commit()
        key_dict = key.to_dict()
        key_dict['user_uid'] = key.user_uid
        return jsonify(key_dict), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to update SSH key {key_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to update SSH key"}), 500


@sshk_bp.route('/admin/sshkeys/<int:key_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_sshkey(key_id):
    """Admin endpoint to delete any SSH key."""
    key = UserSSHKey.query.get_or_404(key_id)
    if ContainerInstance.query.filter_by(ssh_key_id=key_id).first():
        return jsonify({"message": "Cannot delete key: It is currently assigned to one or more containers."}), 409
    try:
        db.session.delete(key)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to delete SSH key {key_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to delete SSH key"}), 500