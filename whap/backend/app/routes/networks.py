from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from ..models import Network, StaticAddress, ComputeServer
from .addresses import is_valid_ip
from ..services import permissions_service
from .. import admin_required
from .. import db

ntwrk_bp = Blueprint('networks', __name__)


@ntwrk_bp.route('/my-networks', methods=['GET'])
@login_required
def get_my_networks():
    """Gets a list of networks the current user has access to via their server permissions."""
    try:
        user_id = current_user.get_id()
        permissions = permissions_service.get_user_permissions(user_id)
        accessible_server_ids = permissions.get('accessible_server_ids', [])

        # If user is admin or has universal access, return all networks
        if accessible_server_ids == '*':
            all_networks = Network.query.order_by(Network.name).all()
            return jsonify([n.to_dict() for n in all_networks]), 200

        # If user has no server access, return empty list
        if not accessible_server_ids:
            return jsonify([]), 200

        # Find distinct network IDs linked to the user's accessible servers
        # via the StaticAddress table.
        network_ids_query = db.session.query(StaticAddress.network_id).distinct() \
            .join(StaticAddress.available_servers) \
            .filter(ComputeServer.id.in_(accessible_server_ids))

        # Fetch the actual Network objects based on the retrieved IDs
        networks = Network.query.filter(Network.id.in_(network_ids_query)).order_by(Network.name).all()

        return jsonify([n.to_dict() for n in networks]), 200
    except Exception as e:
        current_app.logger.error(f"Failed to get networks for user {current_user.get_id()}: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve available networks"), 500


@ntwrk_bp.route('/admin/networks', methods=['GET'])
@login_required
@admin_required
def admin_get_networks():
    """Admin endpoint to list all networks."""
    try:
        networks = Network.query.order_by(Network.name).all()
        return jsonify([n.to_dict() for n in networks]), 200
    except Exception as e:
        current_app.logger.error(f"Admin failed to get networks: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve networks"), 500


@ntwrk_bp.route('/admin/networks', methods=['POST'])
@login_required
@admin_required
def admin_create_network():
    """Admin endpoint to create a new network."""
    data = request.get_json()
    name = data.get('name')
    base_ip = data.get('base_ip')
    prefix_size_str = data.get('prefix_size')
    gateway = data.get('gateway')

    # --- Validation ---
    if not all([name, base_ip, prefix_size_str, gateway]):
        return jsonify({"message": "Name, Base IP, Subnet Size, and Gateway are required"}), 400

    if not is_valid_ip(base_ip) or not is_valid_ip(gateway):
        return jsonify({"message": "Invalid format for Base IP or Gateway IP"}), 400

    try:
        prefix_size = int(prefix_size_str)
        # Assuming IPv4 for this range check
        if not (8 <= prefix_size <= 30):
            raise ValueError("Prefix size out of sensible range")
    except (ValueError, TypeError):
        return jsonify({"message": "Invalid Subnet Size (must be an integer, e.g., 24)"}), 400

    if Network.query.filter(func.lower(Network.name) == func.lower(name)).first():
        return jsonify({"message": f"Network name '{name}' already exists."}), 409
    # --- End Validation ---

    try:
        new_network = Network(
            name=name.strip(),
            base_ip=base_ip.strip(),
            prefix_size=prefix_size,
            gateway=gateway.strip()
        )
        db.session.add(new_network)
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} created Network: {name}")
        return jsonify(new_network.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to create network '{name}': {e}", exc_info=True)
        return jsonify({"message": "Failed to create network"}), 500


@ntwrk_bp.route('/admin/networks/<int:network_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_network(network_id):
    """Admin endpoint to update a network."""
    network = Network.query.get_or_404(network_id)
    data = request.get_json()
    # Get fields, defaulting to existing values
    name = data.get('name', network.name)
    base_ip = data.get('base_ip', network.base_ip)
    prefix_size_str = data.get('prefix_size', network.prefix_size)
    gateway = data.get('gateway', network.gateway)

    # --- Validation (similar to create) ---
    if not all([name, base_ip, prefix_size_str, gateway]):
        return jsonify({"message": "Name, Base IP, Subnet Size, and Gateway cannot be empty"}), 400
    # ... (add full validation as in POST) ...
    try:
        prefix_size = int(prefix_size_str)
    except (ValueError, TypeError):
        return jsonify({"message": "Invalid Subnet Size"}), 400
    # Check for name conflict on a *different* object
    if Network.query.filter(func.lower(Network.name) == func.lower(name), Network.id != network_id).first():
        return jsonify({"message": f"Network name '{name}' already exists."}), 409
    # --- End Validation ---

    try:
        network.name = name.strip()
        network.base_ip = base_ip.strip()
        network.prefix_size = prefix_size
        network.gateway = gateway.strip()
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} updated Network ID {network_id}")
        return jsonify(network.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to update network {network_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to update network"}), 500


@ntwrk_bp.route('/admin/networks/<int:network_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_network(network_id):
    """Admin endpoint to delete a network."""
    network = Network.query.get_or_404(network_id)

    # --- Constraint Check ---
    # Check if any StaticAddress records are still using this network
    if network.static_addresses.first():
        return jsonify({"message": "Cannot delete network: It is still in use by one or more static addresses."}), 409

    try:
        db.session.delete(network)
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} deleted Network ID {network_id} (Name: {network.name})")
        return '', 204  # No Content
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to delete network {network_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to delete network"}), 500