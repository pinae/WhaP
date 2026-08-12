from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from ..models import StaticAddress, Network, ComputeServer
from ..services import permissions_service
from .. import admin_required
from .. import db
import ipaddress
import re

sadr_bp = Blueprint('addresses', __name__)


# --- Helper for IP/MAC validation ---
def is_valid_ip(ip_str):
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


def is_valid_mac(mac_str):
    # Basic MAC format check (e.g., 00:1A:2B:3C:4D:5E or 00-1A-...)
    # Python's ipaddress doesn't handle MACs directly
    # Use a regex for basic format validation
    if re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', mac_str):
        return True
    return False


@sadr_bp.route('/my-static_addresses', methods=['GET'])
@login_required
def get_my_static_addresses():
    """Gets a list of static addresses available on servers the user has access to."""
    try:
        user_id = current_user.get_id()
        permissions = permissions_service.get_user_permissions(user_id)
        accessible_server_ids = permissions.get('accessible_server_ids', [])

        # Base query with eager loading to prevent N+1 queries during serialization
        query = StaticAddress.query.options(
            joinedload(StaticAddress.available_servers),
            joinedload(StaticAddress.assigned_container)
        )

        # If user is not an admin, filter addresses by their accessible servers
        if accessible_server_ids != '*':
            if not accessible_server_ids:
                return jsonify([]), 200  # No servers means no accessible addresses
            query = query.join(StaticAddress.available_servers).filter(ComputeServer.id.in_(accessible_server_ids))

        addresses = query.order_by(StaticAddress.ip_address).all()

        # Deduplicate results, as an address might be on multiple servers the user can see
        unique_addresses = {addr.id: addr for addr in addresses}.values()

        return jsonify([addr.to_dict(include_servers=True) for addr in unique_addresses]), 200
    except Exception as e:
        current_app.logger.error(f"User failed to get their available static addresses: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve static addresses"), 500


@sadr_bp.route('/admin/static_addresses', methods=['GET'])
@login_required
@admin_required
def admin_get_static_addresses():
    """Admin endpoint to list all static IP/MAC addresses."""
    try:
        # Eager load servers to avoid N+1 queries when creating dicts
        addresses = StaticAddress.query.options(
            joinedload(StaticAddress.available_servers),
            joinedload(StaticAddress.assigned_container)  # Also load container info
        ).order_by(StaticAddress.ip_address).all()  # Order by IP?

        # Include server IDs in the dict representation
        return jsonify([addr.to_dict(include_servers=True) for addr in addresses]), 200
    except Exception as e:
        current_app.logger.error(f"Admin failed to get static addresses: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve static addresses"), 500


@sadr_bp.route('/admin/static_addresses', methods=['POST'])
@login_required
@admin_required
def admin_create_static_address():
    """Admin endpoint to create a new static IP/MAC address."""
    data = request.get_json()
    ip_addr = data.get('ip_address')
    mac_addr = data.get('mac_address')
    comment = data.get('comment')
    available_server_ids = data.get('available_server_ids', [])  #
    network_id = data.get('network_id')

    # --- Validation ---
    if not all([ip_addr, mac_addr, network_id]):
        return jsonify({"message": "IP, MAC, and Network selection are required"}), 400
    if not is_valid_ip(ip_addr):
        return jsonify({"message": "Invalid IP address format"}), 400
    if not is_valid_mac(mac_addr):
        return jsonify({"message": "Invalid MAC address format (use XX:XX:XX:XX:XX:XX)"}), 400
    # Check if network exists
    if not db.session.get(Network, network_id):
        return jsonify({"message": "Selected network does not exist."}), 404

    # Normalize MAC to uppercase with colons
    mac_addr = mac_addr.upper().replace('-', ':')

    # Check uniqueness
    if StaticAddress.query.filter_by(ip_address=ip_addr).first():
        return jsonify({"message": f"IP address '{ip_addr}' already exists."}), 409
    if StaticAddress.query.filter(func.upper(StaticAddress.mac_address) == mac_addr.upper()).first():
        return jsonify({"message": f"MAC address '{mac_addr}' already exists."}), 409

    if not isinstance(available_server_ids, list):
        return jsonify({"message": "'available_server_ids' must be a list."}), 400
    # --- End Validation ---

    try:
        # Find valid ComputeServer objects for the relationship
        available_servers = []
        if available_server_ids:
            available_servers = ComputeServer.query.filter(ComputeServer.id.in_(available_server_ids)).all()
            # Optional: Check if all requested IDs were found
            if len(available_servers) != len(set(available_server_ids)):
                current_app.logger.warning("Some server IDs provided for static address assignment were not found.")

        new_address = StaticAddress(
            ip_address=ip_addr,
            mac_address=mac_addr,
            comment=comment,
            network_id=network_id,
            available_servers=available_servers  # Assign the relationship
        )
        db.session.add(new_address)
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} created StaticAddress: IP {ip_addr}, MAC {mac_addr}")
        # Return dict including server IDs
        return jsonify(new_address.to_dict(include_servers=True)), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to create static address {ip_addr}: {e}", exc_info=True)
        return jsonify({"message": "Failed to create static address"}), 500


@sadr_bp.route('/admin/static_addresses/<int:addr_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_static_address(addr_id):
    """Admin endpoint to update a static IP/MAC address and its server availability."""
    address = StaticAddress.query.options(joinedload(StaticAddress.available_servers)).get_or_404(
        addr_id)  # Load servers
    data = request.get_json()

    # Get fields to update
    ip_addr = data.get('ip_address', address.ip_address)  # Default to existing if not provided
    mac_addr = data.get('mac_address', address.mac_address)
    comment = data.get('comment', address.comment)
    network_id = data.get('network_id')
    # Allow updating server assignments
    available_server_ids = data.get('available_server_ids')  # None if not in request
    # Check if network exists
    network = db.session.get(Network, network_id)
    if not network:
        return jsonify({"message": "Selected network does not exist."}), 404

    # --- Validation ---
    if not all([ip_addr, mac_addr, network_id]):
        return jsonify({"message": "IP, MAC, and Network are required"}), 400
    if not is_valid_ip(ip_addr):
        return jsonify({"message": "Invalid IP address format"}), 400
    if not is_valid_mac(mac_addr):
        return jsonify({"message": "Invalid MAC address format (use XX:XX:XX:XX:XX:XX)"}), 400

    mac_addr = mac_addr.upper().replace('-', ':')

    # Check uniqueness (excluding self)
    if StaticAddress.query.filter(StaticAddress.ip_address == ip_addr, StaticAddress.id != addr_id).first():
        return jsonify({"message": f"IP address '{ip_addr}' already exists."}), 409
    if StaticAddress.query.filter(func.upper(StaticAddress.mac_address) == mac_addr.upper(),
                                  StaticAddress.id != addr_id).first():
        return jsonify({"message": f"MAC address '{mac_addr}' already exists."}), 409

    if available_server_ids is not None and not isinstance(available_server_ids, list):
        return jsonify({"message": "'available_server_ids' must be a list if provided."}), 400
    # --- End Validation ---

    try:
        address.ip_address = ip_addr
        address.mac_address = mac_addr
        address.network_id = network_id
        address.comment = comment

        # Update server assignments if provided
        if available_server_ids is not None:
            current_app.logger.debug(
                f"Updating server assignments for address {addr_id} to IDs: {available_server_ids}")
            # Find valid ComputeServer objects for the relationship
            if available_server_ids:
                available_servers = ComputeServer.query.filter(ComputeServer.id.in_(available_server_ids)).all()
                # Optional: Check if all requested IDs were found
                if len(available_servers) != len(set(available_server_ids)):
                    current_app.logger.warning(
                        f"Some server IDs provided for static address update {addr_id} were not found.")
                address.available_servers = available_servers  # Replace assignments
            else:
                address.available_servers = []  # Clear assignments if empty list provided

        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} updated StaticAddress ID {addr_id}")
        # Eager load again before returning to ensure servers are included
        updated_address = db.session.get(
            StaticAddress, addr_id,
            options=[joinedload(StaticAddress.available_servers),
                     joinedload(StaticAddress.assigned_container)]
        )
        return jsonify(updated_address.to_dict(include_servers=True)), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to update static address {addr_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to update static address"}), 500


@sadr_bp.route('/admin/static_addresses/<int:addr_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_static_address(addr_id):
    """Admin endpoint to delete a static IP/MAC address."""
    address = StaticAddress.query.get_or_404(addr_id)

    # Check if address is currently assigned
    if address.assigned_container:
        return jsonify({
            "message": f"Cannot delete address: Currently assigned to container ID {address.assigned_container.id}"}), 409

    try:
        # Manually clear relationships if needed (SQLAlchemy might handle cascade depending on config)
        address.available_servers = []
        db.session.delete(address)
        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} deleted StaticAddress ID {addr_id} (IP: {address.ip_address})")
        return jsonify({"message": "Static address deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to delete static address {addr_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to delete static address"}), 500


@sadr_bp.route('/admin/static_addresses/<int:addr_id>/free', methods=['POST'])
@login_required
@admin_required
def admin_free_static_address(addr_id):
    """Admin endpoint to free a static address by unlinking it from its container."""
    address = StaticAddress.query.get_or_404(addr_id)

    # Check if the address is actually assigned to a container
    if not address.assigned_container:
        return jsonify({"message": "Address is already free."}), 409  # Conflict

    container = address.assigned_container
    container_id_log = container.id

    try:
        # The core logic: simply set the foreign key on the container to NULL
        container.static_address_id = None
        db.session.commit()

        current_app.logger.info(
            f"Admin {current_user.username} freed StaticAddress ID {addr_id} (IP: {address.ip_address}) from Container ID {container_id_log}")

        # Eager load relationships again to return the updated address state
        updated_address = db.session.get(
            StaticAddress, addr_id,
            options=[joinedload(StaticAddress.available_servers),
                     joinedload(StaticAddress.assigned_container)]
        )

        return jsonify(updated_address.to_dict(include_servers=True)), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to free static address {addr_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to free the static address"}), 500
