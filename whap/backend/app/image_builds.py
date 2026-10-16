"""`flask build-images`: build worker roles' shared images and push them to the registry.

Containers don't need this: the first one that needs an image pulls it from
the registry, or builds and pushes it (roles/common_tasks/tasks/shared_image.yml).
Running it after a change to a role, or on a test rig before the tests, means
no user waits for a build.
"""
import os
import sys
import uuid

import ansible_runner
import click
import yaml
from flask import current_app
from flask.cli import with_appcontext

from . import db
from .models import ComputeServer
from .services.ansible_service import runner_path, write_job_inventory
from .services.compose_builder import SHARED_IMAGE_ROLES, _docker_registry
from .services.images import image_tag, role_dir, shared_image_name


def one_role_per_image(roles):
    """The first of ``roles`` for each image they run: a system's synced_ and local_
    roles share one image, which is built once."""
    chosen = {}
    for role in roles:
        chosen.setdefault((shared_image_name(role), image_tag(role)), role)
    return list(chosen.values())


def build_playbook(hostname, roles, registry):
    """A play that runs each role's build tasks (tasks/build.yml) on ``hostname``."""
    return [{
        'hosts': hostname,
        'become': True,
        'gather_facts': False,
        'tasks': [{
            'name': f"Image {shared_image_name(role)} (of {role})",
            'ansible.builtin.include_role': {'name': role, 'tasks_from': 'build'},
            'vars': {'service_cfg': {'image_name': role, 'shared_image': shared_image_name(role),
                                     'whap_registry': registry, 'image_tag': image_tag(role)}},
        } for role in roles],
    }]


WHERE_TO_RUN = ("Run it where WhaP's Ansible jobs run, in the worker container: "
                "docker exec -it whap-worker flask build-images ...")


def check_can_run_ansible(app, inventory_dir):
    """Ansible needs the inventory (host_vars, SSH settings) and a writable runner
    directory. In a deployment only the worker container has both; the backend
    container has neither, and runs as another user."""
    if not os.path.isdir(inventory_dir):
        raise click.ClickException(f"There is no Ansible inventory at {inventory_dir} here. {WHERE_TO_RUN}")
    for directory in (runner_path(app), inventory_dir):
        if not os.access(directory, os.W_OK):
            raise click.ClickException(f"{directory} is not writable here. {WHERE_TO_RUN}")


@click.command("build-images")
@click.option("--server", "hostname", required=True, help="The compute server to build on, as WhaP lists it.")
@click.argument("roles", nargs=-1)
@with_appcontext
def build_images_command(hostname, roles):
    """Build the shared images of ROLES on a compute server and push them to the registry.

    Without ROLES: every worker role with a shared image. An image the server or
    the registry already has (same role files, same tag) is not built again.
    """
    app = current_app._get_current_object()
    server = db.session.scalar(db.select(ComputeServer).filter_by(hostname=hostname))
    if server is None:
        raise click.ClickException(f"No compute server '{hostname}'.")
    available = sorted(role for role in SHARED_IMAGE_ROLES if role_dir(role))
    unknown = sorted(set(roles) - set(available))
    if unknown:
        raise click.ClickException(f"Not a role with a shared image here: {', '.join(unknown)}. "
                                   f"Known: {', '.join(available)}")
    roles = one_role_per_image(list(roles) or available)

    registry = _docker_registry()
    for role in roles:
        click.echo(f"  {(registry + '/') if registry else ''}{shared_image_name(role)}:{image_tag(role)}")
    if not registry:
        click.echo(f"No DOCKER_REGISTRY: the images are built on {hostname} only.")

    inventory_dir = os.path.join(app.config['ANSIBLE_PROJECT_DIR'], 'inventory')
    check_can_run_ansible(app, inventory_dir)

    run_id = f"images_{uuid.uuid4().hex[:8]}"
    playbook_path = runner_path(app, 'playbooks', f'{run_id}.yml')
    os.makedirs(os.path.dirname(playbook_path), exist_ok=True)
    with open(playbook_path, 'w') as f:
        yaml.safe_dump(build_playbook(hostname, roles, registry), f, sort_keys=False)
    hosts_file = write_job_inventory(inventory_dir, run_id, server)
    private_data_dir = runner_path(app, run_id)
    os.makedirs(private_data_dir, exist_ok=True)
    try:
        runner = ansible_runner.run(
            private_data_dir=private_data_dir,
            project_dir=app.config.get('ANSIBLE_PROJECT_DIR'),
            playbook=playbook_path,
            inventory=inventory_dir,
            process_isolation=False,
            rotate_artifacts=1,
            quiet=False,  # the build's progress goes to this terminal
            envvars={
                'ANSIBLE_ROLES_PATH': app.config.get('ANSIBLE_ROLES_PATH', ''),
                'ANSIBLE_PRIVATE_KEY_FILE': app.config.get('ANSIBLE_SSH_PRIVATE_KEY_FILE'),
                'PYTHONUNBUFFERED': '1',
            })
    finally:
        os.remove(hosts_file)
        os.remove(playbook_path)
    if runner.status != 'successful':
        click.echo(f"Building the images failed ({runner.status}, rc {runner.rc}).", err=True)
        sys.exit(1)
    click.echo("Done.")
