from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from ..models import ComputeServer, ContainerInstance
from .. import admin_required
from .. import db
import re

srv_bp = Blueprint('servers', __name__)


@srv_bp.route('/servers', methods=['GET'])
@login_required
def get_servers():
    servers = ComputeServer.query.order_by(ComputeServer.hostname).all()
    return jsonify([s.to_dict() for s in servers]), 200


@srv_bp.route('/admin/servers', methods=['POST'])
@login_required
@admin_required
def admin_create_server():
    """Admin endpoint to create a new compute server."""
    data = request.get_json()
    hostname = data.get('hostname')
    ssh_port_str = data.get('ssh_port', '22')
    gpu_count_str = data.get('gpu_count', '1')

    if not hostname:
        return jsonify({"message": "Hostname is required"}), 400

    # Basic validation - prevent empty strings, maybe check format slightly
    hostname = hostname.strip()
    if not hostname:
        return jsonify({"message": "Hostname cannot be empty"}), 400
    # Example regex: Allow letters, numbers, hyphen, dot (adjust if needed)
    if not re.match(r'^[a-zA-Z0-9.-]+$', hostname):
        return jsonify({"message": "Invalid hostname format."}), 400

    # Check if hostname already exists
    existing = ComputeServer.query.filter(db.func.lower(ComputeServer.hostname) == db.func.lower(hostname)).first()
    if existing:
        return jsonify({"message": f"Hostname '{hostname}' already exists."}), 409  # Conflict

    # Validate port number
    try:
        ssh_port = int(ssh_port_str)
        if not (1 <= ssh_port <= 65535):
            raise ValueError("Port out of range")
    except (ValueError, TypeError):
        return jsonify({"message": "Invalid SSH port (must be an integer between 1-65535)"}), 400

    # Validate GPU count
    try:
        gpu_count = int(gpu_count_str)
        if not (gpu_count >= 0):
            raise ValueError("GPU count cannot be negative")
    except (ValueError, TypeError):
        return jsonify({"message": "Invalid GPU count (must be a valid integers >= 0)"}), 400

    try:
        new_server = ComputeServer(hostname=hostname, ssh_port=ssh_port, gpu_count=gpu_count)
        db.session.add(new_server)
        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} created ComputeServer: {hostname}:{ssh_port} (ID: {new_server.id})")
        return jsonify(new_server.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin {current_user.username} failed to create server {hostname}: {e}",
                                 exc_info=True)
        return jsonify({"message": "Failed to create server"}), 500


@srv_bp.route('/admin/servers/<int:server_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_server(server_id):
    """Admin endpoint to update an existing compute server."""
    server = ComputeServer.query.get_or_404(server_id)
    data = request.get_json()
    hostname = data.get('hostname')
    ssh_port_str = data.get('ssh_port')
    gpu_count_str = data.get('gpu_count')

    if not hostname:
        return jsonify({"message": "Hostname is required"}), 400

    # Basic validation
    hostname = hostname.strip()
    if not hostname:
        return jsonify({"message": "Hostname cannot be empty"}), 400
    if not re.match(r'^[a-zA-Z0-9.-]+$', hostname):
        return jsonify({"message": "Invalid hostname format."}), 400

    # Check if the *new* hostname already exists on a *different* server
    existing = ComputeServer.query.filter(
        db.func.lower(ComputeServer.hostname) == db.func.lower(hostname),
        ComputeServer.id != server_id
    ).first()
    if existing:
        return jsonify({"message": f"Hostname '{hostname}' already exists on another server."}), 409  # Conflict

    # Validate port number
    ssh_port = server.ssh_port  # Keep existing if not provided
    if ssh_port_str is not None:
        try:
            ssh_port = int(ssh_port_str)
            if not (1 <= ssh_port <= 65535):
                raise ValueError("Port out of range")
        except (ValueError, TypeError):
            return jsonify({"message": "Invalid SSH port (must be an integer between 1-65535)"}), 400

    # Validate GPU count
    gpu_count = server.gpu_count  # Keep existing if not provided
    if gpu_count_str is not None:
        try:
            gpu_count = int(gpu_count_str)
            if not (gpu_count >= 0):
                raise ValueError("GPU count cannot be negative")
        except (ValueError, TypeError):
            return jsonify({"message": "Invalid GPU count (must be a valid integer)"}), 400

    try:
        server.hostname = hostname
        server.ssh_port = ssh_port
        server.gpu_count = gpu_count
        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} updated ComputeServer ID {server_id} to hostname: {hostname}")
        return jsonify(server.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin {current_user.username} failed to update server {server_id}: {e}",
                                 exc_info=True)
        return jsonify({"message": "Failed to update server"}), 500


@srv_bp.route('/admin/servers/<int:server_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_server(server_id):
    server = ComputeServer.query.get_or_404(server_id)
    # !!! Check if containers exist on this server before deleting !!!
    if ContainerInstance.query.filter_by(compute_server_id=server_id).filter(
            ContainerInstance.status != 'DELETED').first():
        return jsonify({"message": "Cannot delete server: Containers are still assigned to it."}), 409  # Conflict
    try:
        db.session.delete(server)
        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} deleted ComputeServer ID {server_id} (Hostname: {server.hostname})")
        return jsonify({"message": "Server deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        # ... error logging ...
        return jsonify({"message": "Failed to delete server"}), 500