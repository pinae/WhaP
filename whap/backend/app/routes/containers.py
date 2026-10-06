from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import select, not_
from datetime import datetime, timedelta, timezone
from ..models import ContainerInstance, AnsibleJob, Project, UserSSHKey, LocalUser
from ..models import ComputeServer, StaticAddress, Network
from ..services import permissions_service, volume_service
from .. import admin_required
from .. import db
from .. import socketio
import json
import os
import re

cont_bp = Blueprint('containers', __name__)


def check_container_permission(container_id):
    """Helper to check if current user can manage the container (owner or admin)."""
    container = db.get_or_404(ContainerInstance, container_id)
    is_owner = False
    user_linkage_filter_data = current_user.get_container_user_dict()
    if container.user_local_user_id and container.user_local_user_id == user_linkage_filter_data.get(
            'user_local_user_id'):
        is_owner = True
    elif container.user_uid and container.user_uid == user_linkage_filter_data.get('user_uid'):
        is_owner = True

    if not is_owner and not current_user.is_admin:
        return None, (jsonify(message="Access denied."), 403)

    return container, None  # Return container and no error


def parse_gpu_request(raw, server):
    """Turn the requested GPUs into a sorted list of index strings.

    Accepts a comma-separated string or a list. No GPUs may be sent as None,
    '', [] or 'none' -- the frontend sends 'none' -- and comes back as [].
    Every index must exist on ``server``. Returns (gpus, error_message).
    """
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in ('', 'none')):
        return [], None
    items = raw.split(',') if isinstance(raw, str) else raw
    if not isinstance(items, list):
        return None, "GPUs must be a comma-separated list of GPU numbers, or 'none'."
    gpus = set()
    for item in items:
        text = str(item).strip()
        if not re.fullmatch(r'[0-9]+', text):  # not isdigit(): it accepts '²', which int() rejects
            return None, f"'{text}' is not a GPU number."
        if int(text) >= server.gpu_count:
            return None, f"{server.hostname} has no GPU {text} (it has {server.gpu_count})."
        gpus.add(str(int(text)))
    return sorted(gpus, key=int), None


def queue_action_job(container, action, optimistic_status):
    """Helper to create an AnsibleJob for a container action."""
    if container.status in ['DELETING', 'DELETED', 'PENDING']:
        return jsonify({"message": f"Container cannot be actioned in its current state ({container.status})"}), 409

    container.status = optimistic_status
    new_job = AnsibleJob(
        container_instance_id=container.id,
        server_id=container.compute_server_id,
        status='PENDING',
        action=action
    )
    db.session.add(new_job)
    db.session.commit()
    current_app.logger.info(f"Queued job {new_job.id} for action '{action}' on container {container.id}")
    return jsonify(
        {"message": f"{action.capitalize()} request sent", "container": container.to_dict(), "job_id": new_job.id}), 202


def queue_prolong_ttl_job(container, new_ttl_date):
    """Helper to create an AnsibleJob for a prolong action."""
    if container.status not in ['RUNNING', 'STOPPED', 'PAUSED']:
        return jsonify({"message": f"Container ttl cannot be prolonged in its current state ({container.status})"}), 409

    extravars_data = {'ttl_date': new_ttl_date.strftime('%Y-%m-%d')}
    new_job = AnsibleJob(
        container_instance_id=container.id,
        server_id=container.compute_server_id,
        status='PENDING',
        action='prolong',
        extravars=json.dumps(extravars_data)
    )
    db.session.add(new_job)
    db.session.commit()
    current_app.logger.info(f"Queued job {new_job.id} for action 'prolong ttl' on container {container.id}")
    return jsonify(
        {"message": "Prolong ttl request sent", "container": container.to_dict(), "job_id": new_job.id}), 202


@cont_bp.route('/containers', methods=['GET'])
@login_required
def get_containers():
    user_linkage_filter_data = current_user.get_container_user_dict()
    user_filter = {k: v for k, v in user_linkage_filter_data.items() if v is not None}
    query = ContainerInstance.query.filter(ContainerInstance.status != 'DELETED').filter_by(**user_filter)
    user_containers = query.order_by(ContainerInstance.created_at.desc()).all()
    return jsonify([c.to_dict() for c in user_containers]), 200


@cont_bp.route('/containers/<int:id_no>', methods=['GET'])
@login_required
def get_container(id_no):
    container = db.get_or_404(ContainerInstance, id_no)
    is_owner = False
    user_linkage_filter_data = current_user.get_container_user_dict()
    if container.user_local_user_id and container.user_local_user_id == user_linkage_filter_data.get(
            'user_local_user_id'):
        is_owner = True
    elif container.user_uid and container.user_uid == user_linkage_filter_data.get('user_uid'):
        is_owner = True

    if not is_owner:
        # Check if current user is admin - allow admins to view any container
        if current_user.is_admin:
            current_app.logger.info(f"Admin user {current_user.username} accessing container {id_no}")
        else:
            current_app.logger.warning(f"User {current_user.get_id()} denied access to container {id_no}")
            return jsonify(message="Container not found or access denied"), 404

    return jsonify(container.to_dict()), 200


@cont_bp.route('/containers', methods=['POST'])
@login_required
def create_container():
    data = request.get_json()
    project_id = data.get('projectId')
    server_id = data.get('serverId')
    image_name = data.get('imageName')
    ssh_key_id = data.get('sshKeyId')
    password = data.get('password')
    ttl_date_str = data.get('ttlDate')
    cpu_limit_input = data.get('cpuLimit')
    wants_public_ip = data.get('wants_public_ip', False)
    additional_volumes = data.get('additional_volumes', [])

    # --- Validate inputs ---
    if not all([project_id, server_id, image_name]):
        return jsonify({"message": "Missing required fields (Project, Server, Image)"}), 400

    # --- Find associated objects and check ownership/validity ---
    # Find project BELONGING TO CURRENT USER
    owner_filter_data = current_user.get_project_owner_dict()
    project = Project.query.filter_by(id=project_id, **owner_filter_data).first()

    if not project:
        return jsonify({"message": "Project not found or you don't have access"}), 404

    server = db.session.get(ComputeServer, server_id)
    if not server:
        return jsonify({"message": "Invalid server ID"}), 404

    gpus, gpu_error = parse_gpu_request(data.get('gpus'), server)
    if gpu_error:
        return jsonify({"message": gpu_error}), 400

    ssh_key = None
    if ssh_key_id:
        # Find SSH key BELONGING TO CURRENT USER (using prefixed ID)
        ssh_key = UserSSHKey.query.filter_by(id=ssh_key_id, user_uid=current_user.get_id()).first()
        if not ssh_key:
            return jsonify({"message": "Selected SSH Key not found or invalid"}), 404

    ttl_date = None
    if ttl_date_str:
        try:
            ttl_date = datetime.fromisoformat(ttl_date_str)
        except (ValueError, TypeError):
            return jsonify({"message": "Invalid TTL date format. Please use YYYY-MM-DD."}), 400

    # --- CPU Limit Validation ---
    cpu_limit = None
    if cpu_limit_input is not None and cpu_limit_input != "unlimited":
        try:
            cpu_limit = float(cpu_limit_input)
            if cpu_limit <= 0:
                return jsonify({"message": "CPU limit must be strictly positive"}), 400
        except ValueError:
            return jsonify({"message": "Invalid CPU limit format"}), 400

    # Check Permissions
    user_perms = permissions_service.get_user_permissions(current_user.get_id())

    # Check Server Access
    if '*' not in user_perms['accessible_server_ids'] and server_id not in user_perms['accessible_server_ids']:
        return jsonify({"message": "You do not have access to this compute server."}), 403

    # Check CPU Limit Permission
    allowed_cpu_limit = user_perms.get('cpu_limits', {}).get(server_id)
    # If allowed_cpu_limit is None, it means UNLIMITED access.
    # If allowed_cpu_limit is a number, user is capped at that number.

    if allowed_cpu_limit is not None:
        # User has a limit.
        if cpu_limit is None:
            return jsonify({
                "message": f"You are limited to {allowed_cpu_limit} CPUs on this server. You cannot request unlimited."
            }), 403
        if cpu_limit > allowed_cpu_limit:
            return jsonify({
                "message": f"Requested CPU limit ({cpu_limit}) exceeds your allowed limit ({allowed_cpu_limit})."
            }), 403
    # If allowed_cpu_limit is None (Unlimited), user can request anything (None or any float).

    # Check Additional Volume Permissions.
    # Users have root inside their container, so an unauthorized bind mount is a
    # host / cross-tenant compromise. Enforce the same allowed set that
    # /shared-volumes presents, BEFORE allocating an IP or creating any rows.
    volumes_ok, volumes_error = volume_service.validate_requested_volumes(
        current_user, additional_volumes
    )
    if not volumes_ok:
        current_app.logger.warning(
            f"User {current_user.get_id()} denied container create due to volume request: {volumes_error}"
        )
        return jsonify({"message": volumes_error}), 403

    # --- End validation ---

    # --- Calculate the directory path ---
    app_config = current_app.config
    ansible_user_param = current_user.username
    user_linkage_data = current_user.get_container_user_dict()
    container_base_dir = app_config.get('ANSIBLE_CONTAINER_BASE_DIR', '/docker')
    container_directory = os.path.join(container_base_dir, image_name, ansible_user_param, project.name)

    # --- Find and Assign Static Address ---
    assigned_address = None
    try:
        # Subquery to find IDs of addresses currently assigned to non-deleted containers
        # Ensure correct table/column names after migrations!
        subquery = select(ContainerInstance.static_address_id) \
            .where(ContainerInstance.static_address_id.isnot(None)) \
            .where(ContainerInstance.status != 'DELETED')

        # Base query to find a free address for the selected server
        base_query = StaticAddress.query \
            .join(StaticAddress.available_servers) \
            .filter(ComputeServer.id == server.id) \
            .filter(StaticAddress.id.notin_(subquery)) \
            .join(StaticAddress.network)  # Join with Network to filter by name

        # Apply filter based on user's public/private IP preference
        if wants_public_ip:
            ip_type_log_msg = "public"
            address_query = base_query.filter(Network.name.like('%public'))
        else:
            ip_type_log_msg = "private"
            address_query = base_query.filter(not_(Network.name.like('%public')))

        # Find the first address that is available for the selected server
        # AND is not currently assigned (its ID is not in the subquery results)
        # Use pessimistic locking to prevent race conditions
        with db.session.begin_nested():  # Use nested transaction or lock acquisition
            free_address = address_query \
                .order_by(StaticAddress.id) \
                .with_for_update(skip_locked=True) \
                .first()

            if not free_address:
                current_app.logger.error(
                    f"No free static IP addresses available for server {server.hostname} (ID: {server.id})")
                return jsonify({
                    "message": f"No free IP addresses available for server {server.hostname}. Please contact admin."
                }), 503  # Service Unavailable

            # Address found, store it for later use
            assigned_address = free_address
            current_app.logger.info(
                f"Assigning static address {assigned_address.ip_address} (ID: {assigned_address.id}) to new container.")

        container = ContainerInstance(
            **user_linkage_data,
            project_id=project.id,
            compute_server_id=server.id,
            image_name=image_name,
            ssh_key_id=ssh_key.id if ssh_key else None,
            gpus=','.join(gpus),
            status='PENDING',
            static_address_id=assigned_address.id,
            directory_path=container_directory,
            cpu_limit=cpu_limit,
            ttl_date=ttl_date
        )
        db.session.add(container)
        db.session.commit()

        current_app.logger.info(
            f"Container record created ID: {container.id} for user {current_user.get_id()} on project {project.name}")

        # Create a job record
        extravars_data = {}
        if password and len(password) > 0:
            extravars_data['container_password'] = password
        if ttl_date:
            extravars_data['ttl_date'] = ttl_date.strftime('%Y-%m-%d')
        if additional_volumes:
            extravars_data['additional_volumes'] = additional_volumes
        new_job = AnsibleJob(
            container_instance_id=container.id,
            server_id=server.id,
            status='PENDING',
            action='create',
            extravars=json.dumps(extravars_data)
        )
        db.session.add(new_job)
        container.status = 'STARTING'
        db.session.commit()

        current_app.logger.info(
            f"Queued AnsibleJob ID: {new_job.id} for Container ID: {container.id}"
        )

        # 2. Inform the frontend that the job is queued
        # The frontend will now use the job_id to listen for logs
        socketio.emit('job_created', new_job.to_dict(), room=str(new_job.id))

        return jsonify({'container': container.to_dict(), 'job_id': new_job.id}), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating container DB record for user {current_user.get_id()}: {e}")
        return jsonify({"message": "Failed to create container record"}), 500


@cont_bp.route('/containers/<int:id_no>', methods=['DELETE'])
@login_required
def delete_container(id_no):
    container, error_response = check_container_permission(id_no)
    if error_response: return error_response
    return queue_action_job(container, 'delete', 'DELETING')


# Container Actions (Pause, Resume, Stop, Delete)
@cont_bp.route('/containers/<int:id_no>/pause', methods=['POST'])
@login_required
def pause_container(id_no):
    container, error_response = check_container_permission(id_no)
    if error_response: return error_response
    if container.status not in ['RUNNING']:
        return jsonify({"message": "Container must be running to be paused"}), 400
    return queue_action_job(container, 'pause', 'PAUSING')


@cont_bp.route('/containers/<int:id_no>/resume', methods=['POST'])
@login_required
def resume_container(id_no):
    container, error_response = check_container_permission(id_no)
    if error_response: return error_response
    if container.status not in ['PAUSED', 'STOPPED']:
        return jsonify({"message": "Container must be paused or stopped to be resumed"}), 400
    action = 'unpause' if container.status == 'PAUSED' else 'start'
    return queue_action_job(container, action, 'STARTING')


@cont_bp.route('/containers/<int:id_no>/stop', methods=['POST'])
@login_required
def stop_container(id_no):
    container, error_response = check_container_permission(id_no)
    if error_response: return error_response
    return queue_action_job(container, 'stop', 'STOPPING')


@cont_bp.route('/containers/<int:id_no>/prolong', methods=['POST'])
@login_required
def prolong_container(id_no):
    container, error_response = check_container_permission(id_no)
    if error_response: return error_response

    try:
        current_ttl = container.ttl_date or datetime.now(timezone.utc)
        new_ttl = current_ttl + timedelta(weeks=4)
        container.ttl_date = new_ttl
        db.session.commit()

        # Now queue the Ansible job to update the file on the host
        return queue_prolong_ttl_job(container, new_ttl)

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to prolong container ttl {id_no}: {e}", exc_info=True)
        return jsonify({"message": "Failed to update TTL date"}), 500


@cont_bp.route('/admin/containers', methods=['GET'])
@login_required
@admin_required
def admin_get_containers():
    """Admin endpoint to list ALL non-deleted containers."""
    try:
        all_containers = ContainerInstance.query.filter(ContainerInstance.status != 'DELETED') \
            .order_by(ContainerInstance.created_at.desc()).all()
        # Use the extended to_dict or ensure owner info is clear
        return jsonify([c.to_dict() for c in all_containers]), 200
    except Exception as e:
        current_app.logger.error(f"Admin failed to get containers: {e}")
        return jsonify(message="Failed to retrieve containers"), 500


@cont_bp.route('/admin/containers', methods=['POST'])
@login_required
@admin_required
def admin_create_container_record():
    """
    Admin endpoint to forcefully create ONLY the container database record.
    This does not trigger any Ansible jobs. Use to fix DB inconsistencies.
    """
    data = request.get_json()
    current_app.logger.warning(
        f"Admin {current_user.username} initiating direct DB create for a new Container record with data: {data}")

    # --- Validation ---
    required_fields = ['project_id', 'compute_server_id', 'image_name', 'status', 'user_identifier']
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({"message": f"Missing one or more required fields: {', '.join(required_fields)}"}), 400

    user_identifier = data['user_identifier']
    user_linkage_data = {}
    try:
        user_type, user_id = user_identifier.split(':', 1)
        if user_type == 'local':
            if not db.session.get(LocalUser, int(user_id)):
                return jsonify({"message": f"Local user with ID {user_id} not found."}), 404
            user_linkage_data['user_local_user_id'] = int(user_id)
        elif user_type == 'ldap':
            user_linkage_data['user_uid'] = user_id
        else:
            raise ValueError("Invalid user type prefix")
    except (ValueError, TypeError):
        return jsonify({"message": "Invalid user_identifier format. Must be 'local:<id>' or 'ldap:<uid>'."}), 400

    if not db.session.get(Project, data['project_id']):
        return jsonify({"message": "Project not found."}), 404
    if not db.session.get(ComputeServer, data['compute_server_id']):
        return jsonify({"message": "Compute Server not found."}), 404

    static_address_id = data.get('static_address_id')
    if static_address_id:
        addr = db.session.get(StaticAddress, static_address_id)
        if not addr:
            return jsonify({"message": "Static Address not found."}), 404
        if addr.assigned_container:
            return jsonify({
                "message": f"Static Address {addr.ip_address} is already in use by container #{addr.assigned_container.id}."}), 409

    try:
        new_container = ContainerInstance(
            **user_linkage_data,
            project_id=data['project_id'],
            compute_server_id=data['compute_server_id'],
            image_name=data['image_name'],
            status=data['status'],
            gpus=data.get('gpus'),
            ssh_key_id=data.get('ssh_key_id') or None,
            static_address_id=static_address_id or None,
            container_name=data.get('container_name'),
            directory_path=data.get('directory_path'),
        )
        db.session.add(new_container)
        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} successfully created Container DB record ID {new_container.id}")
        return jsonify(new_container.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Admin {current_user.username} failed to directly create container record: {e}", exc_info=True)
        return jsonify({"message": "Failed to create container record in database"}), 500


@cont_bp.route('/admin/containers/<int:container_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_container_record(container_id):
    """Admin endpoint to forcefully update a container database record."""
    container = db.get_or_404(ContainerInstance, container_id)
    data = request.get_json()
    current_app.logger.warning(
        f"Admin {current_user.username} initiating direct DB update for Container ID {container_id} with data: {data}")

    try:
        # User reassignment
        if 'user_identifier' in data and data['user_identifier']:
            user_identifier = data['user_identifier']
            user_type, user_id = user_identifier.split(':', 1)
            if user_type == 'local':
                if not db.session.get(LocalUser, int(user_id)):
                    return jsonify({"message": f"Local user with ID {user_id} not found."}), 404
                container.user_local_user_id = int(user_id)
                container.user_uid = None
            elif user_type == 'ldap':
                container.user_uid = user_id
                container.user_local_user_id = None
            else:
                return jsonify({"message": "Invalid user_identifier format."}), 400

        # Static address reassignment
        if 'static_address_id' in data:
            new_addr_id = data['static_address_id'] or None
            if new_addr_id and new_addr_id != container.static_address_id:
                addr = db.session.get(StaticAddress, new_addr_id)
                if not addr:
                    return jsonify({"message": "Static Address not found."}), 404
                if addr.assigned_container:
                    return jsonify({
                        "message": f"Static Address {addr.ip_address} is already in use by container #{addr.assigned_container.id}."}), 409
            container.static_address_id = new_addr_id

        # Foreign key fields
        if 'project_id' in data and data['project_id']:
            if not db.session.get(Project, data['project_id']):
                return jsonify({"message": "Project not found."}), 404
            container.project_id = data['project_id']

        if 'compute_server_id' in data and data['compute_server_id']:
            if not db.session.get(ComputeServer, data['compute_server_id']):
                return jsonify({"message": "Compute Server not found."}), 404
            container.compute_server_id = data['compute_server_id']

        # Simple string/null fields
        simple_fields = ['image_name', 'status', 'gpus', 'container_name', 'directory_path']
        for field in simple_fields:
            if field in data:
                setattr(container, field, data[field] or None)

        if 'ssh_key_id' in data:
            container.ssh_key_id = data['ssh_key_id'] or None

        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} successfully updated Container DB record ID {container_id}")
        return jsonify(container.to_dict()), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Admin {current_user.username} failed to directly update container record {container_id}: {e}",
            exc_info=True)
        return jsonify({"message": "Failed to update container record in database"}), 500


@cont_bp.route('/admin/containers/<int:container_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_container_record(container_id):
    """
    Admin endpoint to forcefully delete ONLY the container database record.
    This DOES NOT guarantee stopping the actual container process on the host.
    It primarily serves as a cleanup mechanism for orphaned records in case of errors.
    """
    container = db.get_or_404(ContainerInstance, container_id)
    current_app.logger.warning(
        f"Admin {current_user.username} initiating direct DB delete for Container ID {container_id} (Image: {container.image_name})")

    try:
        # --- IMPORTANT: Release assigned static IP address ---
        if container.static_address_id:
            # Fetch the address to log which one is being released
            address = db.session.get(StaticAddress, container.static_address_id)
            ip_being_released = address.ip_address if address else f"ID {container.static_address_id}"
            current_app.logger.info(
                f"Releasing static address {ip_being_released} associated with deleted container {container_id}")
            # Setting FK to None on the container record is enough before delete,
            # but explicitly nullifying might be needed if cascade rules aren't set.
            # For safety, we can nullify before delete, though SQLAlchemy might handle it.
            container.static_address_id = None
            db.session.add(container)  # Stage the change
            db.session.flush()  # Apply FK change before delete potentially

        # Delete the container record itself
        db.session.delete(container)
        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} successfully deleted Container DB record ID {container_id}")
        # Return 204 No Content is standard for successful DELETE with no body
        return '', 204

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Admin {current_user.username} failed to directly delete container record {container_id}: {e}",
            exc_info=True)
        return jsonify({"message": "Failed to delete container record from database"}), 500
