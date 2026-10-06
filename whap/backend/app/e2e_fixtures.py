"""Seed and reset the infrastructure the end-to-end tests run on.

    flask e2e-seed SPEC     create or update the rows a test run needs
    flask e2e-reset SPEC    remove what the test users created

SPEC is a YAML file (see whap/e2e/seed.example.yml), or ``-`` for stdin so it
can be piped into a running container:

    docker exec -i whap-backend flask e2e-seed - < seed.yml

Seeding is idempotent: it creates what is missing and updates what exists to
match the spec, but never takes over rows it does not own -- an address the
spec lists that already belongs to another network is an error, not a move.

Reset removes the *test data* -- the members' containers, projects, shares,
SSH keys and group memberships -- and keeps the infrastructure, which the next
seed would only recreate. ``--all`` removes the seeded infrastructure as well.

Both commands refuse to run unless E2E_FIXTURES_ENABLED is set, because reset
deletes the listed users' projects and queues deletion of their directories.
"""
import ipaddress
import os
import re

import click
import yaml
from flask import current_app
from flask.cli import with_appcontext

from . import db
from .models import (ComputeServer, ContainerInstance, Group, GroupCpuLimit, GroupGpuAccess,
                     GroupMembership, Network, Project, ProjectShare, StaticAddress, UserSSHKey)
from .services.task_queue_service import enqueue_delete_directory

DATASET_MARKER = 'e2e-marker.txt'
DATASET_MARKER_CONTENT = 'whap-e2e-dataset'
_MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
_HOSTNAME_RE = re.compile(r'^[a-zA-Z0-9.-]+$')


class E2EFixtureError(click.ClickException):
    """A problem the operator has to fix; click prints it without a traceback."""


# --- Spec ---------------------------------------------------------------------

def load_spec(data):
    """Validate a parsed spec and return it normalised. Raises E2EFixtureError."""
    if not isinstance(data, dict):
        raise E2EFixtureError("The spec must be a YAML mapping.")
    problems = []

    servers = []
    for i, raw in enumerate(data.get('servers') or []):
        hostname = str(raw.get('hostname', '')).strip()
        if not _HOSTNAME_RE.match(hostname):
            problems.append(f"servers[{i}].hostname '{hostname}' is not a valid hostname.")
        servers.append({'hostname': hostname,
                        'ssh_port': int(raw.get('ssh_port', 22)),
                        'gpu_count': int(raw.get('gpu_count', 1))})
    if not servers:
        problems.append("servers: list at least one compute server.")

    net = data.get('network') or {}
    network = None
    try:
        subnet = ipaddress.ip_network(f"{net.get('base_ip')}/{net.get('prefix_size')}", strict=True)
        gateway = ipaddress.ip_address(str(net.get('gateway')))
        network = {'name': str(net.get('name', '')).strip(), 'base_ip': str(subnet.network_address),
                   'prefix_size': subnet.prefixlen, 'gateway': str(gateway), 'subnet': subnet}
        if not network['name']:
            problems.append("network.name is required.")
        # Container creation picks private addresses with NOT LIKE '%public';
        # a test network named like a public one would leave none to pick.
        if network['name'].lower().endswith('public'):
            problems.append(f"network.name '{network['name']}' ends in 'public', which marks public "
                            "networks: containers asking for a private address would find none.")
        if not 8 <= subnet.prefixlen <= 30:
            problems.append("network.prefix_size must be between 8 and 30.")
        if gateway not in subnet:
            problems.append(f"network.gateway {gateway} is outside {subnet}.")
    except ValueError as e:
        problems.append(f"network: {e}")

    addresses = []
    for i, raw in enumerate(data.get('addresses') or []):
        ip, mac = str(raw.get('ip', '')), str(raw.get('mac', ''))
        try:
            parsed = ipaddress.ip_address(ip)
            if network and parsed not in network['subnet']:
                problems.append(f"addresses[{i}].ip {ip} is outside {network['subnet']}.")
            elif network and ip in (network['gateway'], network['base_ip'],
                                    str(network['subnet'].broadcast_address)):
                problems.append(f"addresses[{i}].ip {ip} is the gateway, network or broadcast address.")
        except ValueError:
            problems.append(f"addresses[{i}].ip '{ip}' is not an IP address.")
        if not _MAC_RE.match(mac):
            problems.append(f"addresses[{i}].mac '{mac}' is not a MAC address (aa:bb:cc:dd:ee:ff).")
        addresses.append({'ip': ip, 'mac': mac.lower()})
    if not addresses:
        problems.append("addresses: list at least one address for containers.")
    for key in ('ip', 'mac'):
        values = [a[key] for a in addresses]
        if len(values) != len(set(values)):
            problems.append(f"addresses: each {key} may appear only once.")

    grp = data.get('group') or {}
    members = [str(m) for m in grp.get('members') or []]
    for m in members:
        if not re.match(r'^(ldap:[^:\s]+|local:\d+)$', m):
            problems.append(f"group.members: '{m}' must be 'ldap:<uid>' or 'local:<id>'.")
    if not members:
        problems.append("group.members: list the test users.")
    images = grp.get('images', '*')
    gpus = str(grp.get('gpus', 'all'))
    if gpus != 'all' and not re.match(r'^\d+(,\d+)*$', gpus):
        problems.append(f"group.gpus '{gpus}' must be 'all' or a list like '0,1'.")
    cpu_limit = grp.get('cpu_limit')
    if cpu_limit is not None and (not isinstance(cpu_limit, (int, float)) or cpu_limit <= 0):
        problems.append("group.cpu_limit must be a positive number, or null for unlimited.")
    group = {'name': str(grp.get('name', '')).strip(), 'members': members, 'gpus': gpus,
             'images': '*' if images == '*' else ','.join(images or []), 'cpu_limit': cpu_limit}
    if not group['name']:
        problems.append("group.name is required.")

    if problems:
        raise E2EFixtureError("Invalid e2e spec:\n  - " + "\n  - ".join(problems))
    return {'servers': servers, 'network': network, 'addresses': addresses,
            'group': group, 'dataset': data.get('dataset')}


def _require_test_rig():
    if not current_app.config.get('E2E_FIXTURES_ENABLED'):
        raise E2EFixtureError(
            "E2E_FIXTURES_ENABLED is not set, so this is not a test rig. Enable the whap "
            "role's e2e switch (service_cfg.e2e.enabled) on test deployments only.")


# --- Seed ---------------------------------------------------------------------

def seed(spec):
    """Create or update everything the spec describes. Returns a list of report lines."""
    _require_test_rig()
    report = []

    servers = []
    for s in spec['servers']:
        server = db.session.scalar(db.select(ComputeServer).filter(
            db.func.lower(ComputeServer.hostname) == s['hostname'].lower()))
        report.append(f"server {s['hostname']}: {'updated' if server else 'created'}")
        if not server:
            server = ComputeServer(hostname=s['hostname'])
            db.session.add(server)
        server.ssh_port, server.gpu_count = s['ssh_port'], s['gpu_count']
        servers.append(server)

    n = spec['network']
    network = db.session.scalar(db.select(Network).filter_by(name=n['name']))
    report.append(f"network {n['name']} ({n['base_ip']}/{n['prefix_size']}): "
                  f"{'updated' if network else 'created'}")
    if not network:
        network = Network(name=n['name'])
        db.session.add(network)
    network.base_ip, network.prefix_size, network.gateway = n['base_ip'], n['prefix_size'], n['gateway']
    db.session.flush()

    for a in spec['addresses']:
        address = db.session.scalar(db.select(StaticAddress).filter_by(ip_address=a['ip']))
        if address and address.network_id != network.id:
            raise E2EFixtureError(f"Address {a['ip']} already belongs to network "
                                  f"'{address.network.name}'; the spec may not take it over.")
        clash = db.session.scalar(db.select(StaticAddress).filter(
            db.func.lower(StaticAddress.mac_address) == a['mac'], StaticAddress.ip_address != a['ip']))
        if clash:
            raise E2EFixtureError(f"MAC {a['mac']} is already used by address {clash.ip_address}.")
        if not address:
            address = StaticAddress(ip_address=a['ip'], network_id=network.id)
            db.session.add(address)
        address.mac_address = a['mac']
        address.available_servers = list(servers)
    report.append(f"addresses: {len(spec['addresses'])} on {', '.join(s.hostname for s in servers)}")

    g = spec['group']
    group = db.session.scalar(db.select(Group).filter_by(name=g['name']))
    report.append(f"group {g['name']}: {'updated' if group else 'created'}, "
                  f"members {', '.join(g['members'])}")
    if not group:
        group = Group(name=g['name'])
        db.session.add(group)
    group.image_whitelist = g['images']
    db.session.flush()
    group.compute_servers = list(servers)
    db.session.execute(db.delete(GroupGpuAccess).filter_by(group_id=group.id))
    db.session.execute(db.delete(GroupCpuLimit).filter_by(group_id=group.id))
    db.session.execute(db.delete(GroupMembership).filter_by(group_id=group.id))
    for server in servers:
        db.session.add(GroupGpuAccess(group_id=group.id, compute_server_id=server.id, allowed_gpus=g['gpus']))
        db.session.add(GroupCpuLimit(group_id=group.id, compute_server_id=server.id, cpu_limit=g['cpu_limit']))
    for uid in g['members']:
        db.session.add(GroupMembership(group_id=group.id, user_uid=uid, is_group_admin=False))

    if spec['dataset']:
        report.append(check_dataset(spec['dataset']))

    db.session.commit()
    return report


def check_dataset(name):
    """Confirm the dataset the whap role creates is there and readable."""
    base = current_app.config.get('DATASETS_BASE_PATH') or ''
    marker = os.path.join(base, name, DATASET_MARKER)
    try:
        with open(marker) as f:
            content = f.read().strip()
    except OSError as e:
        raise E2EFixtureError(
            f"Dataset marker {marker} is not readable ({e.strerror}). The whap role creates it "
            "when service_cfg.e2e.enabled is set; datasets are mounted read-only, so the "
            "application cannot.")
    if content != DATASET_MARKER_CONTENT:
        raise E2EFixtureError(f"{marker} contains '{content}', expected '{DATASET_MARKER_CONTENT}'.")
    return f"dataset {name}: present"


# --- Reset --------------------------------------------------------------------

def _member_filters(members):
    """Owner and user columns for the test users. The models disagree on
    prefixes: memberships and SSH keys store 'ldap:<uid>', while projects and
    containers store the bare LDAP uid or the local user id."""
    ldap_uids = [m.split(':', 1)[1] for m in members if m.startswith('ldap:')]
    local_ids = [int(m.split(':', 1)[1]) for m in members if m.startswith('local:')]
    projects = db.or_(Project.owner_uid.in_(ldap_uids), Project.owner_local_user_id.in_(local_ids))
    containers = db.or_(ContainerInstance.user_uid.in_(ldap_uids),
                        ContainerInstance.user_local_user_id.in_(local_ids))
    return projects, containers


def reset(spec, force=False, include_infrastructure=False, keep_project_dirs=False):
    """Remove what the test users created. Returns a list of report lines."""
    _require_test_rig()
    report = []
    members = spec['group']['members']
    projects_filter, containers_filter = _member_filters(members)

    # Container rows stand for containers that may still run on a compute
    # server. Deleting the row would orphan them, so stop unless told otherwise.
    containers = db.session.scalars(db.select(ContainerInstance).filter(containers_filter)).all()
    if containers and not force:
        listing = "\n  ".join(f"#{c.id} {c.container_name or '(unnamed)'} on {c.compute_server.hostname}: "
                              f"{c.status}" for c in containers)
        raise E2EFixtureError(
            f"The test users still have {len(containers)} container(s):\n  {listing}\n"
            "Delete them through WhaP so they are removed from the compute server, or pass "
            "--force to delete only the database records.")
    for c in containers:
        report.append(f"container #{c.id} {c.container_name or ''}: record deleted -- "
                      f"remove it on {c.compute_server.hostname} by hand if it still exists")
        c.static_address_id = None
        db.session.delete(c)
    db.session.flush()

    for project in db.session.scalars(db.select(Project).filter(projects_filter)).all():
        if not keep_project_dirs:
            path = os.path.join(current_app.config['PROJECT_STORAGE_DIR'], project.owner_dir_name, project.name)
            enqueue_delete_directory(path)
        report.append(f"project {project.owner_dir_name}/{project.name}: deleted"
                      + ("" if keep_project_dirs else ", directory queued for deletion"))
        db.session.delete(project)

    shares = db.session.execute(db.delete(ProjectShare).filter(ProjectShare.user_uid.in_(members))).rowcount
    keys = db.session.execute(db.delete(UserSSHKey).filter(UserSSHKey.user_uid.in_(members))).rowcount
    report.append(f"shares with the test users: {shares} deleted; their SSH keys: {keys} deleted")

    # Groups the test users made through the UI have only test users in them.
    seeded_group = spec['group']['name']
    for group in db.session.scalars(db.select(Group).filter(Group.id != 0, Group.name != seeded_group)).all():
        uids = {m.user_uid for m in group.members}
        if uids and uids <= set(members):
            report.append(f"group {group.name}: deleted (only test users)")
            db.session.delete(group)
    db.session.flush()
    memberships = db.session.execute(db.delete(GroupMembership).filter(
        GroupMembership.user_uid.in_(members),
        GroupMembership.group_id.in_(db.select(Group.id).filter(Group.name != seeded_group)))).rowcount
    report.append(f"other group memberships of the test users: {memberships} deleted")

    if include_infrastructure:
        report.extend(_remove_infrastructure(spec))

    db.session.commit()
    return report


def _remove_infrastructure(spec):
    report = []
    group = db.session.scalar(db.select(Group).filter_by(name=spec['group']['name']))
    if group:
        db.session.delete(group)
        report.append(f"group {group.name}: deleted")

    network = db.session.scalar(db.select(Network).filter_by(name=spec['network']['name']))
    for a in spec['addresses']:
        address = db.session.scalar(db.select(StaticAddress).filter_by(ip_address=a['ip']))
        if not address or (network and address.network_id != network.id):
            continue
        if address.assigned_container:
            raise E2EFixtureError(f"Address {a['ip']} is assigned to container "
                                  f"#{address.assigned_container.id}; not removing infrastructure.")
        db.session.delete(address)
    db.session.flush()
    if network:
        if db.session.scalar(db.select(StaticAddress).filter_by(network_id=network.id)):
            report.append(f"network {network.name}: kept, other addresses still use it")
        else:
            db.session.delete(network)
            report.append(f"network {network.name}: deleted")

    for s in spec['servers']:
        server = db.session.scalar(db.select(ComputeServer).filter(
            db.func.lower(ComputeServer.hostname) == s['hostname'].lower()))
        if not server:
            continue
        # Checked by hand: the test database (SQLite) does not enforce foreign
        # keys, so a dangling reference would only fail on Postgres.
        in_use_by = []
        if server.containers.first():
            in_use_by.append("containers")
        if server.accessible_by_groups.first():
            in_use_by.append("other groups' access")
        if db.session.scalar(db.select(GroupGpuAccess).filter_by(compute_server_id=server.id)):
            in_use_by.append("other groups' GPU rules")
        if db.session.scalar(db.select(GroupCpuLimit).filter_by(compute_server_id=server.id)):
            in_use_by.append("other groups' CPU limits")
        if in_use_by:
            report.append(f"server {server.hostname}: kept, still used by {', '.join(in_use_by)}")
        else:
            db.session.delete(server)
            report.append(f"server {server.hostname}: deleted")
    return report


# --- CLI ----------------------------------------------------------------------

def _read_spec(stream):
    try:
        return load_spec(yaml.safe_load(stream))
    except yaml.YAMLError as e:
        raise E2EFixtureError(f"The spec is not valid YAML: {e}")


@click.command('e2e-seed')
@click.argument('spec', type=click.File('r'))
@with_appcontext
def e2e_seed_command(spec):
    """Create or update the rows an end-to-end test run needs (SPEC: YAML file, or - for stdin)."""
    for line in seed(_read_spec(spec)):
        click.echo(line)


@click.command('e2e-reset')
@click.argument('spec', type=click.File('r'))
@click.option('--force', is_flag=True,
              help="Delete the test users' container records even though the containers may still "
                   "exist on a compute server.")
@click.option('--all', 'include_infrastructure', is_flag=True,
              help="Also remove the seeded group, addresses, network and servers.")
@click.option('--keep-project-dirs', is_flag=True,
              help="Delete project records but leave their directories in place.")
@with_appcontext
def e2e_reset_command(spec, force, include_infrastructure, keep_project_dirs):
    """Remove what the end-to-end test users created (SPEC: YAML file, or - for stdin)."""
    for line in reset(_read_spec(spec), force=force, include_infrastructure=include_infrastructure,
                      keep_project_dirs=keep_project_dirs):
        click.echo(line)
