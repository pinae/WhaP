from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from ..models import Group, GroupMembership, GroupGpuAccess, ComputeServer, GroupCpuLimit
from ..services import permissions_service
from ..user_management import load_user
from .. import admin_required
from .. import db

grp_bp = Blueprint('groups', __name__)


@grp_bp.route('/groups/search', methods=['GET'])
@login_required
def search_groups():
    """Searches for groups to be used in project sharing."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    groups = Group.query.filter(Group.name.ilike(f'%{q}%')).limit(10).all()
    results = []
    for group in groups:
        # Exclude the special 'Admins' group from being shareable
        if group.id == 0:
            continue
        results.append({
            'id': f"group:{group.id}",
            'display_name': f"{group.name} (Group)"
        })
    return jsonify(results)


@grp_bp.route('/groups', methods=['GET'])
@login_required
def get_my_groups():
    """Gets a list of groups the current user is a member of."""
    try:
        user_id = current_user.get_id()
        memberships = GroupMembership.query.filter_by(user_uid=user_id).all()

        groups_data = []
        for membership in memberships:
            group_dict = membership.group.to_dict()
            group_dict['is_group_admin'] = membership.is_group_admin
            groups_data.append(group_dict)

        # Sort by group name
        groups_data.sort(key=lambda x: x['name'])
        return jsonify(groups_data), 200
    except Exception as e:
        current_app.logger.error(f"Failed to get groups for user {current_user.get_id()}: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve user groups"), 500


@grp_bp.route('/groups', methods=['POST'])
@login_required
def create_my_group():
    """Allows a user to create a new group and assign permissions they possess."""
    data = request.get_json()
    name = data.get('name')
    image_whitelist = data.get('image_whitelist', [])
    server_ids = data.get('accessible_server_ids', [])
    gpu_rules = data.get('gpu_access_rules', {})
    cpu_rules = data.get('cpu_access_rules', {})
    members_data = data.get('members', [])

    if not name:
        return jsonify({"message": "Group name is required"}), 400
    if Group.query.filter(func.lower(Group.name) == func.lower(name)).first():
        return jsonify({"message": f"Group name '{name}' already exists."}), 409

    # --- Permission Propagation & Validation ---
    user_perms = permissions_service.get_user_permissions(current_user.get_id())

    # gpu_access_rules wire format is {server_id: "0,1" | "all"} (same as update
    # and as the frontend sends for both create and edit).
    try:
        ok, message = permissions_service.validate_grantable_permissions(
            user_perms,
            server_ids=server_ids,
            image_whitelist=image_whitelist,
            gpu_rules=gpu_rules,
            cpu_rules=cpu_rules,
        )
    except permissions_service.InvalidGrantRequest as e:
        return jsonify({"message": str(e)}), 400
    if not ok:
        return jsonify({"message": message}), 403

    try:
        new_group = Group(
            name=name.strip(),
            image_whitelist=','.join(image_whitelist) if image_whitelist else None
        )
        if server_ids:
            servers = ComputeServer.query.filter(ComputeServer.id.in_(server_ids)).all()
            new_group.compute_servers.extend(servers)

        db.session.add(new_group)
        db.session.flush()

        for server_id in gpu_rules.keys():
            new_gpu_access_rule = GroupGpuAccess(
                group_id=new_group.id,
                compute_server_id=int(server_id),
                allowed_gpus=gpu_rules[server_id],
            )
            db.session.add(new_gpu_access_rule)

        for server_id, rule_val in cpu_rules.items():
            limit_val = None
            if rule_val is not None and rule_val != "unlimited":
                limit_val = float(rule_val)

            new_cpu_rule = GroupCpuLimit(
                group_id=new_group.id,
                compute_server_id=int(server_id),
                cpu_limit=limit_val
            )
            db.session.add(new_cpu_rule)

        all_members = {}
        for member_data in members_data:
            if 'user_uid' in member_data and 'is_group_admin' in member_data:
                all_members[member_data['user_uid']] = member_data['is_group_admin']

        # Ensure the creator is always included and is an admin
        all_members[current_user.get_id()] = True

        new_memberships = [
            GroupMembership(group_id=new_group.id, user_uid=uid, is_group_admin=is_admin)
            for uid, is_admin in all_members.items()
        ]
        if new_memberships:
            db.session.bulk_save_objects(new_memberships)

        db.session.commit()

        group_dict = new_group.to_dict()
        group_dict['is_group_admin'] = True

        return jsonify(group_dict), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User failed to create group '{name}': {e}", exc_info=True)
        return jsonify({"message": "Failed to create group"}), 500


@grp_bp.route('/groups/<int:group_id>', methods=['GET'])
@login_required
def get_my_group_details(group_id):
    """Gets full details for a single group, if the user is a member."""
    user_id = current_user.get_id()
    membership = GroupMembership.query.filter_by(user_uid=user_id, group_id=group_id).first()

    if not membership:
        return jsonify(message="Access denied: You are not a member of this group."), 403

    group = membership.group
    group_dict = group.to_dict()

    # Add member details to the response
    members = []
    for member in group.members:
        members.append({
            'user_uid': member.user_uid,
            'is_group_admin': member.is_group_admin
        })
    group_dict['members'] = members

    return jsonify(group_dict), 200


@grp_bp.route('/groups/<int:group_id>', methods=['PUT'])
@login_required
def update_my_group(group_id):
    """Allows a group admin to update a group they manage."""
    user_id = current_user.get_id()
    membership = GroupMembership.query.filter_by(user_uid=user_id, group_id=group_id).first()

    if not membership or not membership.is_group_admin:
        return jsonify(message="Access denied: You are not an admin of this group."), 403

    group = membership.group
    data = request.get_json()
    image_whitelist = data.get('image_whitelist', [])
    server_ids = data.get('accessible_server_ids', [])
    gpu_rules_dict = data.get('gpu_access_rules', {})
    cpu_rules_dict = data.get('cpu_access_rules', {})
    members_data = data.get('members')

    # --- Permission Propagation & Validation ---
    user_perms = permissions_service.get_user_permissions(user_id)

    # update's wire format for gpu rules is {server_id: "csv"} already.
    try:
        ok, message = permissions_service.validate_grantable_permissions(
            user_perms,
            server_ids=server_ids,
            image_whitelist=image_whitelist,
            gpu_rules=gpu_rules_dict,
            cpu_rules=cpu_rules_dict,
        )
    except permissions_service.InvalidGrantRequest as e:
        return jsonify({"message": str(e)}), 400
    if not ok:
        return jsonify({"message": message}), 403

    # Validate the users list
    admin_found = False
    for member_data in members_data:
        if 'user_uid' not in member_data or 'is_group_admin' not in member_data:
            return jsonify({
                "message": f"All users must have a integer ID (user_id) and is_group_admin must be set as a boolean."
            }), 403
        user_object = load_user(member_data['user_uid'])
        if user_object is None:
            return jsonify({
                "message": f"The user_uid {member_data['user_uid']} does not exist."
            }), 403
        if type(member_data['is_group_admin']) is bool and member_data['is_group_admin']:
            admin_found = True
    if not admin_found:
        return jsonify({
            "message": f"At least one user must have admin status."
        }), 403

    try:
        # Update simple properties
        if 'name' in data and group.id != 0:
            group.name = data['name'].strip()
        if 'image_whitelist' in data:
            group.image_whitelist = ','.join(image_whitelist) or None

        # Update M2M relationships (delete-then-add approach)
        if 'accessible_server_ids' in data:
            servers = ComputeServer.query.filter(ComputeServer.id.in_(server_ids)).all()
            group.compute_servers = servers

        if 'gpu_access_rules' in data:
            GroupGpuAccess.query.filter_by(group_id=group_id).delete()
            for server_id, allowed_gpus in gpu_rules_dict.items():
                db.session.add(GroupGpuAccess(
                    group_id=group_id,
                    compute_server_id=int(server_id),
                    allowed_gpus=allowed_gpus
                ))

        if 'cpu_access_rules' in data:
            GroupCpuLimit.query.filter_by(group_id=group_id).delete()
            for server_id, rule_val in cpu_rules_dict.items():
                limit_val = None
                if rule_val is not None and rule_val != "unlimited":
                    limit_val = float(rule_val)

                db.session.add(GroupCpuLimit(
                    group_id=group_id,
                    compute_server_id=int(server_id),
                    cpu_limit=limit_val
                ))

        if members_data is not None and len(members_data) > 0:
            # Use a delete-then-add strategy
            GroupMembership.query.filter_by(group_id=group_id).delete()
            db.session.flush()  # Apply deletion immediately

            new_members = []
            for member_data in members_data:
                if 'user_uid' in member_data and 'is_group_admin' in member_data:
                    new_members.append(GroupMembership(
                        group_id=group_id,
                        user_uid=member_data['user_uid'],
                        is_group_admin=member_data['is_group_admin']
                    ))
            if new_members:
                db.session.bulk_save_objects(new_members)

        db.session.commit()
        current_app.logger.info(f"User '{user_id}' updated group '{group.name}' (ID: {group_id})")
        group_dict = group.to_dict()
        group_dict['members'] = [
            {'user_uid': m.user_uid, 'is_group_admin': m.is_group_admin} for m in group.members
        ]
        return jsonify(group_dict), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User failed to update group {group_id}: {e}", exc_info=True)
        return jsonify(message="Failed to update group"), 500


@grp_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@login_required
def delete_my_group(group_id):
    """Allows a group admin to delete a group they manage."""
    if group_id == 0:
        return jsonify({"message": "The Admins group cannot be deleted."}), 403

    # Authorization: Ensure current user is a group admin
    membership = GroupMembership.query.filter_by(user_uid=current_user.get_id(), group_id=group_id).first()
    if not membership or not membership.is_group_admin:
        return jsonify(message="Access denied: You are not an admin of this group."), 403

    group = membership.group

    # Safety check: Prevent deletion if the group owns projects
    if group.projects.first():
        return jsonify(
            {"message": "Cannot delete group: It still owns one or more projects. Please reassign them first."}), 409

    try:
        group_name_for_log = group.name
        db.session.delete(group)
        db.session.commit()
        current_app.logger.info(
            f"User {current_user.get_id()} deleted Group ID {group_id} (Name: {group_name_for_log})")
        return '', 204  # No Content
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {current_user.get_id()} failed to delete group {group_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to delete group"}), 500


@grp_bp.route('/admin/groups', methods=['GET'])
@login_required
@admin_required
def admin_get_groups():
    """Admin endpoint to list all groups."""
    try:
        groups = Group.query.order_by(Group.id).all()
        return jsonify([g.to_dict() for g in groups]), 200
    except Exception as e:
        current_app.logger.error(f"Admin failed to get groups: {e}", exc_info=True)
        return jsonify(message="Failed to retrieve groups"), 500


@grp_bp.route('/admin/groups/<int:group_id>', methods=['GET'])
@login_required
@admin_required
def admin_get_group_details(group_id):
    """Admin endpoint to get full details for a single group, including members."""
    group = Group.query.get_or_404(group_id)
    group_dict = group.to_dict()

    members = []
    for member in group.members:
        # Here we'd ideally look up the display name, but for now user_uid is sufficient
        members.append({
            'user_uid': member.user_uid,
            'is_group_admin': member.is_group_admin
        })
    group_dict['members'] = members

    return jsonify(group_dict)


@grp_bp.route('/admin/groups', methods=['POST'])
@login_required
@admin_required
def admin_create_group():
    """Admin endpoint to create a new group."""
    data = request.get_json()
    name = data.get('name')
    image_whitelist_list = data.get('image_whitelist', [])
    server_ids = data.get('accessible_server_ids', [])
    members_data = data.get('members', [])

    if not name:
        return jsonify({"message": "Group name is required"}), 400
    if Group.query.filter(func.lower(Group.name) == func.lower(name)).first():
        return jsonify({"message": f"Group name '{name}' already exists."}), 409

    try:
        new_group = Group(
            name=name.strip(),
            image_whitelist=','.join(image_whitelist_list) if image_whitelist_list else None
        )
        if server_ids:
            servers = ComputeServer.query.filter(ComputeServer.id.in_(server_ids)).all()
            new_group.compute_servers.extend(servers)

        db.session.add(new_group)
        db.session.flush()  # Flush to get new_group.id

        if members_data:
            new_memberships = [
                GroupMembership(
                    group_id=new_group.id,
                    user_uid=member['user_uid'],
                    is_group_admin=member['is_group_admin']
                )
                for member in members_data if 'user_uid' in member and 'is_group_admin' in member
            ]
            if new_memberships:
                db.session.bulk_save_objects(new_memberships)

        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} created Group: {name}")
        return jsonify(new_group.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to create group '{name}': {e}", exc_info=True)
        return jsonify({"message": "Failed to create group"}), 500


@grp_bp.route('/admin/groups/<int:group_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_group(group_id):
    """Admin endpoint to update a group, including its members."""
    group = Group.query.get_or_404(group_id)
    data = request.get_json()

    if 'name' in data:
        new_name = data['name'].strip()
        if not new_name:
            return jsonify({"message": "Group name cannot be empty"}), 400
        if group.id == 0:
            return jsonify({"message": "The Admins group name cannot be changed."}), 403
        if Group.query.filter(func.lower(Group.name) == func.lower(new_name), Group.id != group_id).first():
            return jsonify({"message": f"Group name '{new_name}' already exists."}), 409
        group.name = new_name

    if 'image_whitelist' in data:
        image_whitelist_list = data.get('image_whitelist', [])
        group.image_whitelist = ','.join(image_whitelist_list) if image_whitelist_list else None

    if 'members' in data:
        # Use a delete-then-add strategy for simplicity
        GroupMembership.query.filter_by(group_id=group_id).delete()

        new_members = []
        for member_data in data['members']:
            if 'user_uid' in member_data and 'is_group_admin' in member_data:
                new_members.append(GroupMembership(
                    group_id=group_id,
                    user_uid=member_data['user_uid'],
                    is_group_admin=member_data['is_group_admin']
                ))

        if new_members:
            db.session.bulk_save_objects(new_members)

    try:
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} updated Group ID {group_id}")
        return jsonify(group.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to update group {group_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to update group"}), 500


@grp_bp.route('/admin/groups/<int:group_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_group(group_id):
    """Admin endpoint to delete a group."""
    if group_id == 0:
        return jsonify({"message": "The Admins group cannot be deleted."}), 403

    group = Group.query.get_or_404(group_id)

    if group.projects.first():
        return jsonify({"message": "Cannot delete group: It still owns one or more projects."}), 409

    try:
        db.session.delete(group)
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} deleted Group ID {group_id} (Name: {group.name})")
        return '', 204
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to delete group {group_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to delete group"}), 500
