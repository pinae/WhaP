import math

from ..models import ComputeServer
from ..models import GroupMembership, Group
from .. import db


class InvalidGrantRequest(ValueError):
    """The grant request is malformed -- a client error (400), as opposed to a
    well-formed request for something the user may not grant (403)."""


def _server_id(raw):
    """A server id from the request as an int. JSON object keys always arrive
    as strings, list entries may be either."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise InvalidGrantRequest(f"Invalid server ID '{raw}': server IDs are numbers.")


def validate_grantable_permissions(user_perms, server_ids, image_whitelist,
                                   gpu_rules, cpu_rules):
    """Check that a group creator/admin may grant exactly what they hold.

    Single source of truth for create_my_group / update_my_group. Returns
    ``(ok, message)``; ``message`` is None when everything is grantable.
    Raises InvalidGrantRequest for malformed input (a non-numeric server id,
    an unparseable CPU limit), which the routes answer with 400 rather than
    the 403 of a refused grant.

    Inputs are already parsed from the request:
      * ``server_ids``: list of server ids to grant access to.
      * ``image_whitelist``: list of image names to grant.
      * ``gpu_rules``: ``{server_id: "csv gpu ids" | "all"}`` (keys str or int).
      * ``cpu_rules``: ``{server_id: <float|str|"unlimited"|None>}`` (keys str or int).

    ``user_perms`` is permissions_service.get_user_permissions output. Server-id
    keys are normalised to int here so the int-keyed ``gpu_access`` / ``cpu_limits``
    maps are looked up consistently (the previous inline code mixed int and str
    keys, which could KeyError or silently mis-validate).
    """
    accessible = user_perms['accessible_server_ids']
    has_all_servers = '*' in accessible

    def _has_server(sid):
        return has_all_servers or sid in accessible

    # Server access.
    server_ids = [_server_id(sid) for sid in server_ids]
    if not has_all_servers:
        for sid in server_ids:
            if sid not in accessible:
                return False, f"You do not have permission to grant access to server ID {sid}."

    # Image whitelist.
    if '*' not in user_perms['image_whitelist']:
        for image in image_whitelist:
            if image not in user_perms['image_whitelist']:
                return False, f"You do not have permission to grant access to image '{image}'."

    # GPU access.
    gpu_access = user_perms.get('gpu_access')
    if gpu_access != '*':
        for raw_sid, requested_spec in gpu_rules.items():
            sid = _server_id(raw_sid)
            held = gpu_access.get(sid) if isinstance(gpu_access, dict) else None
            if not held:
                return False, f"You do not have permission to grant access to any GPU on server ID {sid}."
            if held != 'all':
                requested = {g.strip() for g in str(requested_spec).split(',') if g.strip()}
                allowed = {g.strip() for g in held.split(',') if g.strip()}
                if not requested.issubset(allowed):
                    return False, f"You do not have permission to grant access to all requested GPUs for server ID {sid}."

    # CPU limits.
    cpu_limits = user_perms.get('cpu_limits', {})
    for raw_sid, rule_val in cpu_rules.items():
        sid = _server_id(raw_sid)
        if not _has_server(sid):
            return False, f"You do not have permission to grant access to server ID {sid}."

        allowed_limit = cpu_limits.get(sid)

        requested_limit = None  # None == unlimited
        if rule_val is not None and rule_val != "unlimited":
            try:
                requested_limit = float(rule_val)
            except (ValueError, TypeError):
                raise InvalidGrantRequest(f"Invalid CPU limit format for server {sid}")
            # float() accepts "nan", and every comparison with NaN is false, so
            # it would slip past the cap check below.
            if not math.isfinite(requested_limit) or requested_limit <= 0:
                raise InvalidGrantRequest(f"Invalid CPU limit for server {sid}: use a positive number.")

        # A capped user cannot grant unlimited or a higher cap. An uncapped user
        # (allowed_limit is None) may grant anything.
        if allowed_limit is not None:
            if requested_limit is None:
                return False, (f"You are limited to {allowed_limit} CPUs on server {sid}. "
                               "You cannot grant unlimited access.")
            if requested_limit > allowed_limit:
                return False, (f"You cannot grant {requested_limit} CPUs on server {sid}. "
                               f"Your limit is {allowed_limit}.")

    return True, None


def user_can_access_container(user, container):
    """Return True if ``user`` may view/manage ``container`` (its owner or an admin).

    Single source of truth for container ownership, shared by the REST route
    guard (check_container_permission) and the Socket.IO log-room join, so the
    two can't diverge. ``container`` may be None (e.g. unknown id) -> False.
    """
    if container is None:
        return False
    linkage = user.get_container_user_dict()
    if container.user_local_user_id and container.user_local_user_id == linkage.get('user_local_user_id'):
        return True
    if container.user_uid and container.user_uid == linkage.get('user_uid'):
        return True
    return bool(user.is_admin)


def get_user_permissions(user_uid):
    """
    Calculates the total aggregated permissions for a given user by traversing all their groups.
    Handles cyclical group memberships to prevent infinite loops.
    """

    # If user is in the admin group (ID 0), they have universal permissions.
    is_admin = db.session.scalar(db.select(GroupMembership).filter_by(user_uid=user_uid, group_id=0))
    if is_admin:
        servers = ComputeServer.query.all()
        # Admins get "all" GPUs and no CPU cap on every server. We return the
        # same keys and value types as the non-admin path below so callers can
        # treat both uniformly: image_whitelist is always a list (['*'] means
        # "all"), and cpu_limits is always present.
        gpu_map = {server.id: "all" for server in servers}
        cpu_map = {server.id: None for server in servers}
        return {
            'accessible_server_ids': [server.id for server in servers],
            'image_whitelist': ['*'],
            'gpu_access': gpu_map,
            'cpu_limits': cpu_map,
        }

    # Set to track visited group IDs to prevent infinite loops
    visited_groups = set()

    # Get initial list of group IDs the user is directly a member of
    initial_memberships = GroupMembership.query.filter_by(user_uid=user_uid).all()
    groups_to_visit = [m.group_id for m in initial_memberships]

    # Aggregated permissions
    accessible_server_ids = set()
    image_whitelist = set()
    gpu_map = dict()
    cpu_map = dict()

    while groups_to_visit:
        group_id = groups_to_visit.pop(0)
        if group_id in visited_groups:
            continue

        visited_groups.add(group_id)
        group = db.session.get(Group, group_id)
        if not group:
            continue

        # Aggregate accessible servers.
        for server in group.compute_servers:
            accessible_server_ids.add(server.id)

        # Aggregate GPU access rules. This is independent of compute_servers:
        # a group may grant GPU access via rules without the server appearing
        # in its compute_servers relationship, so it must not be nested under
        # the server loop above.
        for rule in group.gpu_access_rules:
            if rule.compute_server_id not in gpu_map:
                gpu_map[rule.compute_server_id] = rule.allowed_gpus
                continue
            if gpu_map[rule.compute_server_id] == "all":
                continue
            if rule.allowed_gpus == "all":
                gpu_map[rule.compute_server_id] = "all"
                continue
            allowed_gpus = set(gpu_map[rule.compute_server_id].split(','))
            for allowed_gpu in rule.allowed_gpus.split(','):
                allowed_gpus.add(allowed_gpu)
            gpu_map[rule.compute_server_id] = ','.join(sorted(allowed_gpus))

        # Aggregate image whitelist
        if group.image_whitelist:
            if '*' in group.image_whitelist:
                # If any group has '*', the user gets all images
                image_whitelist = {'*'}
            elif '*' not in image_whitelist:
                images = {img.strip() for img in group.image_whitelist.split(',')}
                image_whitelist.update(images)

        # Aggregate CPU limits
        for rule in group.cpu_access_rules:
            server_id = rule.compute_server_id

            # Initialize if not present
            if server_id not in cpu_map:
                cpu_map[server_id] = rule.cpu_limit
                continue

            # If current aggregation is "unlimited" (None), it stays unlimited
            if cpu_map[server_id] is None:
                continue

            # If new rule is "unlimited" (None), result becomes unlimited
            if rule.cpu_limit is None:
                cpu_map[server_id] = None
                continue

            # Otherwise, take the maximum of the numeric limits
            cpu_map[server_id] = max(cpu_map[server_id], rule.cpu_limit)

    return {
        'accessible_server_ids': sorted(list(accessible_server_ids)),
        'image_whitelist': sorted(list(image_whitelist)),
        'gpu_access': gpu_map,
        'cpu_limits': cpu_map
    }
