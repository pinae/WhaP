import os
import uuid
import json
import yaml
import random
import string
import ansible_runner
from flask import current_app
from .. import db
from ..models import ComputeServer, UserSSHKey
from ..services.local_file_service import get_gids_for_paths
from .compose_builder import build_compose_file
from .. import socketio


def runner_path(app, *parts):
    """A path under ANSIBLE_RUNNER_DIR, where playbooks and per-job runner data live."""
    return os.path.join(app.config['ANSIBLE_RUNNER_DIR'], *parts)


def write_job_inventory(inventory_dir, job_id, server):
    """Write this job's dynamic host file into the shared inventory directory
    under a per-job filename, and return the path written.

    It must live in the shared inventory dir (alongside ``group_vars`` /
    ``host_vars``, which supply the SSH connection user and key), so ansible
    resolves the right connection settings -- pointing at a bare per-job dir made
    it fall back to connecting as ``root``. The *filename* is per-job, so two
    jobs running concurrently never overwrite one another's target host (the
    original bug was a single shared ``99_dynamic_hosts.ini``). Generated plays
    target a specific hostname, so another job's host file present in the dir is
    simply ignored.
    """
    os.makedirs(inventory_dir, exist_ok=True)
    hosts_file_path = os.path.join(inventory_dir, f'99_dynamic_hosts_job_{job_id}.ini')
    inventory_content_str = f"[job_targets]\n{server.hostname} ansible_port={server.ssh_port}\n"
    with open(hosts_file_path, 'w') as f:
        f.write(inventory_content_str)
    return hosts_file_path


class quoted(str):
    pass


def quoted_presenter(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')


yaml.add_representer(quoted, quoted_presenter)


def execute_ansible_job(job, event_callback):
    """
    Generates and runs an Ansible playbook based on the job's action.
    This function is executed by the worker process.
    It handles container creation, deletion, stopping, pausing, etc.
    It updates the database with the final status of the container.
    """
    app = current_app._get_current_object()

    # No nested app context: the caller (run_job.py) already has one, and the
    # job and container it passes in belong to that context's session. A
    # nested context has its own session, whose commit() saves nothing.
    container = job.container
    server = job.server
    action = job.action

    if not container or not server:
        app.logger.error(f"[Ansible Job {job.id}] Could not find container or server. Aborting.")
        job.status = 'FAILED'
        job.log = "Internal error: Associated container or server not found."
        db.session.commit()
        return 'ERROR', job.log, 'failed', {}

    app.logger.info(
        f"[Ansible Job {job.id}] Starting action '{action}' for container {container.id} on {server.hostname}")
    job.log = f"Starting Ansible job for action: {action}...\n"
    db.session.commit()

    # --- Playbook Generation ---
    playbook_dir = runner_path(app, 'playbooks')
    os.makedirs(playbook_dir, exist_ok=True)
    playbook_path = os.path.join(playbook_dir, f'{action}_{server.id}_{container.id}_{job.id}.yml')

    playbook_content = None
    success_status = 'UNKNOWN'
    failure_status = 'ERROR'

    # --- Playbook Logic based on Action ---
    if action == 'create':
        success_status = 'RUNNING'

        # The `container.user` hybrid property will return the correct wrapper
        # which has the get_ansible_user_params method.
        if not container.user:
            app.logger.error(
                f"[Ansible Job {job.id}] Could not resolve user for container {container.id}. Aborting.")
            job.status = 'FAILED'
            container.status = 'ERROR'
            job.log += "\\nFATAL: User could not be resolved. This might be an LDAP connectivity issue."
            db.session.commit()
            return 'failed', job.log, 'failed', {}

        ansible_user_params = container.user.get_ansible_user_params()
        if not all(ansible_user_params.values()):
            app.logger.error(
                f"[Ansible Job {job.id}] User details (user, user_id, group_id) are incomplete. Aborting.")
            job.status = 'FAILED'
            container.status = 'ERROR'
            job.log += "\\nFATAL: Incomplete user parameters from user object."
            db.session.commit()
            return 'failed', job.log, 'failed', {}

        # --- Load extravars for password and additional volumes ---
        password = ''.join(random.SystemRandom().choice(
            string.ascii_uppercase + string.ascii_lowercase + string.digits
        ) for _ in range(20))  # Default fallback if no password is supplied
        ttl_date = None
        additional_volumes = []
        host_paths_for_gids = []
        if job.extravars:
            try:
                extravars_data = json.loads(job.extravars)
                password = extravars_data.get('container_password', password)
                ttl_date = extravars_data.get('ttl_date')
                raw_volumes = extravars_data.get('additional_volumes', [])
                for vol in raw_volumes:
                    host_path = vol.get('host_path')
                    container_path = vol.get('container_path')
                    if host_path and container_path:
                        host_paths_for_gids.append(host_path)
                        mode = 'rw' if vol.get('is_writable') else 'ro'
                        additional_volumes.append(f"{host_path}:{container_path}:{mode}")
            except json.JSONDecodeError:
                app.logger.warning(f"[Ansible Job {job.id}] Could not decode extravars JSON.")
        # --- End loading extravars ---

        app.logger.info(f"[Ansible Job {job.id}] Getting GIDs for shared folders: {host_paths_for_gids}")
        shared_folder_gids = get_gids_for_paths(host_paths_for_gids)
        app.logger.info(f"[Ansible Job {job.id}] Found GIDs for shared folders: {shared_folder_gids}")

        # --- SSH Key Aggregation ---
        public_key_string = None
        if container.project.owner_group_id:
            app.logger.info(
                f"[Ansible Job {job.id}] Project is owned by group {container.project.owner_group.name}. Aggregating SSH keys.")
            group_members = container.project.owner_group.members
            all_keys = set()
            for member in group_members:
                user_keys = UserSSHKey.query.filter_by(user_uid=member.user_uid).all()
                for key in user_keys:
                    all_keys.add(key.public_key.strip())
            if all_keys:
                public_key_string = "\n".join(sorted(list(all_keys)))
                app.logger.info(f"[Ansible Job {job.id}] Found {len(all_keys)} unique SSH keys for the group.")
        elif container.ssh_key:
            app.logger.info(f"[Ansible Job {job.id}] Using individual user's SSH key.")
            public_key_string = container.ssh_key.public_key.strip()
        # --- End SSH Key Aggregation ---

        project_name = container.project.name
        container_docker_name = f"{container.user.username.lower()}-{project_name.lower()}-{container.id}"

        container_base_dir = app.config.get('ANSIBLE_CONTAINER_BASE_DIR', '/docker')
        container_directory = os.path.join(
            container_base_dir,
            f"{container.image_name}-{container.user.username}-{project_name}")

        # Update container with generated name and path for future actions
        container.container_name = container_docker_name
        container.directory_path = container_directory

        subnet_cidr = f"{container.static_address.network.base_ip}/{container.static_address.network.prefix_size}"

        service_cfg_vars = {
            'user': quoted(container.user.username),
            'user_id': quoted(str(ansible_user_params['user_id'])),
            'group_id': quoted(str(ansible_user_params['group_id'])),
            'additional_gids': [str(gid) for gid in shared_folder_gids],
            'owner': quoted(current_app.config.get("CONTAINER_FILE_OWNER", "pina")),
            'group': quoted('docker'),
            'project': quoted(project_name),
            'project_name': quoted(project_name),
            'safe_project_name': quoted(project_name),
            'directory': quoted(container_directory),
            'gpus': container.gpus.split(',') if container.gpus else [],
            'container_name': quoted(container_docker_name),
            'name': quoted(container_docker_name),
            'image_name': quoted(container.image_name),
            'additional_volumes': additional_volumes,
            'public_key': quoted(public_key_string) if public_key_string else None,
            'password': quoted(password),
            'ttl_date': quoted(ttl_date) if ttl_date else None,
            'network': quoted(container.static_address.network.name),
            'ip_address': quoted(container.static_address.ip_address),
            'mac_address': quoted(container.static_address.mac_address),
            'gateway': quoted(container.static_address.network.gateway),
            'subnet': quoted(subnet_cidr),
            'cpu_limit': container.cpu_limit,
        }

        # Generate Docker Compose content using the Python builder
        compose_content = build_compose_file(
            container_name=container_docker_name,
            role_name=container.image_name,
            user=container.user.username,
            user_id=ansible_user_params['user_id'],
            group_id=ansible_user_params['group_id'],
            password=password,
            project_name=project_name,
            mac_address=container.static_address.mac_address,
            network_name=container.static_address.network.name,
            ipv4_address=container.static_address.ip_address,
            additional_volumes=additional_volumes,
            additional_gids=[str(gid) for gid in shared_folder_gids],
            cpu_limit=container.cpu_limit,
            gpu_selection=container.gpus.split(',') if container.gpus else []
        )
        service_cfg_vars['docker_compose_content'] = quoted(compose_content)

        playbook_content = [{
            'hosts': quoted(server.hostname),
            'become': True,
            'roles': [{'role': quoted(container.image_name), 'vars': {'service_cfg': service_cfg_vars}}]
        }]

    elif action == 'stop':
        success_status = 'STOPPED'
        playbook_content = [{
            'hosts': quoted(server.hostname), 'become': True, 'gather_facts': False, 'tasks': [
                {'name': f'Stop container service for {container.container_name}',
                 'community.docker.docker_container': {
                     'name': quoted(container.container_name),
                     'state': 'stopped'
                 }}
            ]}
        ]

    elif action == 'delete':
        success_status = 'DELETED'
        playbook_content = [{
            'hosts': server.hostname, 'become': True, 'gather_facts': False, 'tasks': [
                {'name': f'Remove container service for {container.container_name}',
                 'community.docker.docker_container': {
                     'name': quoted(container.container_name),
                     'state': 'absent'
                 }}
            ]}
        ]

    elif action == 'prolong':
        success_status = container.status  # Status does not change
        failure_status = container.status
        ttl_date = None
        if job.extravars:
            try:
                extravars_data = json.loads(job.extravars)
                ttl_date = extravars_data.get('ttl_date')
            except json.JSONDecodeError:
                app.logger.warning(f"[Ansible Job {job.id}] Could not decode extravars for prolong.")

        if not ttl_date:
            app.logger.error(
                f"[Ansible Job {job.id}] TTL date not found in extravars for prolong action. Aborting.")
            # Manually fail the job without running Ansible
            return 'failed', "Internal Error: TTL date was missing.", 'failed', {}

        # Define a file path inside the container's host directory to store the TTL
        ttl_file_path = os.path.join(container.directory_path, 'ttl_date.txt')

        ansible_user_params = job.container.user.get_ansible_user_params()

        playbook_content = [{
            'hosts': server.hostname, 'become': True, 'gather_facts': False, 'tasks': [
                {'name': f'Update TTL file for {container.container_name}',
                 'ansible.builtin.copy': {
                     'content': f'{ttl_date}\n',
                     'dest': ttl_file_path,
                     'owner': str(ansible_user_params['user_id']),
                     'group': str(ansible_user_params['group_id']),
                     'mode': '0644'
                 }}
            ]}
        ]

    elif action in ['pause', 'unpause', 'start']:
        docker_command = 'pause' if action == 'pause' else ('unpause' if action == 'unpause' else 'start')
        success_status = 'PAUSED' if action == 'pause' else 'RUNNING'
        playbook_content = [{
            'hosts': server.hostname, 'become': True, 'gather_facts': False, 'tasks': [
                {'name': f'{docker_command.capitalize()} container {container.container_name}',
                 'ansible.builtin.command': f'docker {docker_command} {container.container_name}',
                 'register': 'action_result',
                 'changed_when': "action_result.rc == 0",
                 'failed_when': "action_result.rc != 0"}
            ]}
        ]
    else:
        app.logger.error(f"[Ansible Job {job.id}] Unsupported action '{action}' requested.")
        job.status = 'FAILED'
        job.log += f"\nFATAL: Unsupported action '{action}'."
        db.session.commit()
        return 'ERROR', job.log, 'failed', {}

    # --- Write playbook to file ---
    job.playbook = json.dumps(playbook_content)
    try:
        with open(playbook_path, 'w') as f:
            yaml.dump(playbook_content, f, default_flow_style=False)
        app.logger.info(f"[Ansible Job {job.id}] Generated playbook: {playbook_path}")
        with open(playbook_path, 'r') as f:
            playbook_file_content = f.read()
            job.log += "\n--- Playbook Content ---\n" + playbook_file_content + "\n--- End Playbook Content ---\n"
            db.session.commit()
    except Exception as e:
        app.logger.error(f"[Ansible Job {job.id}] Failed to write playbook: {e}")
        job.status = 'FAILED'
        container.status = 'ERROR'
        job.log += f"\nERROR: Failed to create Ansible playbook file.\n{e}"
        db.session.commit()
        return 'ERROR', job.log, 'failed', {}

    # --- Ansible Runner Configuration ---
    private_data_dir = runner_path(app, f"job_{job.id}")
    os.makedirs(private_data_dir, exist_ok=True)

    # Dynamic inventory: written into the SHARED inventory dir so ansible
    # picks up its group_vars/host_vars (SSH user, key, ...), but under a
    # per-job filename so concurrent jobs never clobber one another.
    inventory_dir = os.path.join(app.config['ANSIBLE_PROJECT_DIR'], 'inventory')
    try:
        hosts_file_path = write_job_inventory(inventory_dir, job.id, server)
        app.logger.info(f"[Ansible Job {job.id}] Wrote dynamic inventory to {hosts_file_path}")
    except IOError as e:
        app.logger.error(f"[Ansible Job {job.id}] FAILED to write inventory file: {e}")
        return 'failed', f'Failed to write inventory: {e}', 'failed', {}

    runner_config = {
        'private_data_dir': private_data_dir,
        'project_dir': app.config.get('ANSIBLE_PROJECT_DIR'),
        'playbook': playbook_path,
        'inventory': inventory_dir,
        'event_handler': event_callback,
        'process_isolation': False,
        'rotate_artifacts': 1,
        'envvars': {
            'ANSIBLE_ROLES_PATH': app.config.get('ANSIBLE_ROLES_PATH', ''),
            'ANSIBLE_PRIVATE_KEY_FILE': app.config.get('ANSIBLE_SSH_PRIVATE_KEY_FILE'),
            'PYTHONUNBUFFERED': '1',
        }
    }

    # --- Run Ansible ---
    runner = ansible_runner.run(**runner_config)

    # --- Process Results ---
    full_log = ""
    try:
        stdout_path = os.path.join(runner.config.artifact_dir, 'stdout')
        if os.path.exists(stdout_path):
            with open(stdout_path, 'r') as f_stdout:
                full_log = f_stdout.read()
        job.log += f"\n--- Ansible STDOUT ---\n{full_log}\n--- End STDOUT ---"
    except Exception as log_err:
        app.logger.error(f"[Ansible Job {job.id}] Error reading action logs: {log_err}")
        job.log += "\nERROR: Could not read Ansible execution logs."

    app.logger.info(f"[Ansible Job {job.id}] Finished with status: {runner.status} (RC: {runner.rc})")

    extra_data_to_save = {}

    if runner.status == 'successful':
        job.status = 'SUCCESSFUL'
        container.status = success_status

        if action == 'create':
            app.logger.info(f"[Ansible Job {job.id}] Container created.")

        extra_data_to_save = {
            'container_name': container.container_name,
            'directory_path': container.directory_path
        }

    else:  # Handle failed, timeout, etc.
        job.status = 'FAILED'
        container.status = failure_status
        job.log += f"\nERROR: Ansible execution failed with status '{runner.status}'."
        app.logger.error(f"[Ansible Job {job.id}] Job FAILED. Status: {runner.status}, RC: {runner.rc}.")

        # If creation fails, release the IP
        if action == 'create' and container.static_address_id:
            app.logger.warning(
                f"[Ansible Job {job.id}] Releasing assigned IP {container.static_address.ip_address} due to creation failure.")
            container.static_address_id = None
            extra_data_to_save = {'static_address_id': None}

    db.session.commit()

    # Clean up playbook file
    try:
        if os.path.exists(playbook_path):
            os.remove(playbook_path)
    except OSError as e:
        app.logger.warning(f"[Ansible Job {job.id}] Could not remove playbook file {playbook_path}: {e}")

    # Clean up this job's dynamic hosts file (unique per job) from the shared
    # inventory dir. group_vars/host_vars in that dir are left untouched.
    try:
        if os.path.exists(hosts_file_path):
            os.remove(hosts_file_path)
    except OSError as e:
        app.logger.warning(f"[Ansible Job {job.id}] Could not remove dynamic hosts file {hosts_file_path}: {e}")

    return container.status, full_log, runner.status, extra_data_to_save


def create_project_directory_async(username, project_name):
    """Runs the project directory creation playbook in a background green thread."""
    app = current_app._get_current_object()
    socketio.start_background_task(run_create_project_directory, app, username, project_name)


def run_create_project_directory(app, username, project_name):
    """
    Generates and runs an Ansible playbook to ensure project directory exists
    on all compute nodes.
    """
    with app.app_context():
        job_id = f"create-dir-{username}-{project_name}-{uuid.uuid4().hex[:6]}"
        app.logger.info(
            f"[{job_id}] Starting Ansible job to create directory for project '{project_name}' user '{username}'")

        # --- Define Target Hosts ---
        try:
            # Get all registered compute server hostnames
            servers = ComputeServer.query.all()
            if not servers:
                app.logger.warning(f"[{job_id}] No compute servers found in DB. Cannot create project directory.")
                # Optionally, update project status or log persistent warning?
                return
            target_hosts = [s.hostname for s in servers]
            app.logger.info(f"[{job_id}] Target hosts for directory creation: {target_hosts}")
        except Exception as e:
            app.logger.error(f"[{job_id}] Failed to query compute servers: {e}")
            return

        # --- Playbook Generation ---
        playbook_dir = runner_path(app, 'playbooks')
        os.makedirs(playbook_dir, exist_ok=True)
        playbook_path = os.path.join(playbook_dir, f'create_dir_{job_id}.yml')

        # Define the path on the target hosts
        # IMPORTANT: Make this configurable or based on a robust convention
        project_base_dir = app.config.get('PROJECT_HOST_BASE_PATH', '/data/projects')  # Example base path
        project_full_path = os.path.join(project_base_dir, username, project_name)

        # Define user/group for ownership - needs alignment with host system setup
        dir_owner = username
        dir_group = app.config.get('PROJECT_HOST_GROUP', username)  # Default group to username? Or a shared group?

        playbook_content = [
            {
                'hosts': 'all',  # Target all hosts in the inventory
                'become': True,  # Need privileges to create directories and set ownership
                'gather_facts': False,
                'tasks': [
                    {
                        'name': f"Ensure project directory exists: {project_full_path}",
                        'ansible.builtin.file': {
                            'path': project_full_path,
                            'state': 'directory',
                            'owner': dir_owner,
                            'group': dir_group,
                            'mode': '0770'
                            # Example permissions (owner/group rwx, others no access) - ADJUST AS NEEDED!
                        }
                    }
                    # Potentially add task to ensure parent dirs exist (e.g., /data/projects/username)
                ]
            }
        ]

        try:
            with open(playbook_path, 'w') as f:
                yaml.dump(playbook_content, f, default_flow_style=False)
            app.logger.info(f"[{job_id}] Generated project directory playbook: {playbook_path}")
        except Exception as e:
            app.logger.error(f"[{job_id}] Failed to write project directory playbook: {e}")
            return

        # --- Ansible Runner Execution ---
        private_data_dir = runner_path(app, job_id)
        os.makedirs(private_data_dir, exist_ok=True)

        # Dynamic inventory for the target hosts
        inventory_content = {'all': {'hosts': {host: {} for host in target_hosts}}}

        runner_config = {
            'private_data_dir': private_data_dir,
            'playbook': playbook_path,
            'inventory': inventory_content,
            'envvars': {
                'ANSIBLE_ROLES_PATH': app.config.get('ANSIBLE_ROLES_PATH', ''),
                'ANSIBLE_PRIVATE_KEY_FILE': app.config.get('ANSIBLE_SSH_PRIVATE_KEY_FILE'),
            },
            'quiet': app.config.get('ANSIBLE_RUNNER_QUIET', True),
            'rotate_artifacts': 1,
        }

        app.logger.info(f"[{job_id}] Starting Ansible Runner for project directory creation.")

        try:
            # Run synchronously within the thread
            runner = ansible_runner.run(**runner_config)
            app.logger.info(f"[{job_id}] Ansible Runner finished. Status: {runner.status}, RC: {runner.rc}")

            if runner.status != 'successful':
                app.logger.error(
                    f"[{job_id}] Failed to create project directory for '{project_name}'. Status: {runner.status}")
                # Log details for debugging
                try:
                    stdout_path = os.path.join(runner.config.artifact_dir, 'stdout')
                    if os.path.exists(stdout_path):
                        with open(stdout_path, 'r') as f_stdout:
                            app.logger.error(f"[{job_id}] Ansible stdout:\n{f_stdout.read(2000)}")  # Log first 2k chars
                except Exception as log_err:
                    app.logger.error(f"[{job_id}] Error reading stdout for failed job: {log_err}")
                # How to notify user? For now, just log error.
            else:
                app.logger.info(
                    f"[{job_id}] Successfully ensured project directory exists for '{project_name}' on target hosts.")

        except Exception as runner_err:
            app.logger.error(f"[{job_id}] Ansible Runner execution failed for project directory creation: {runner_err}")

        finally:
            # Clean up playbook file
            try:
                if os.path.exists(playbook_path):
                    os.remove(playbook_path)
            except OSError as e:
                app.logger.warning(f"[{job_id}] Could not remove playbook file {playbook_path}: {e}")
