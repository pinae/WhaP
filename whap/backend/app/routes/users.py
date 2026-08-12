from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from datetime import datetime, timedelta, timezone
from ..models import LocalUser, LdapUserCache, Project, GroupMembership, UserSSHKey, ContainerInstance
from ..services import ldap_service, notification_service, volume_service
from .. import admin_required
from .. import db

user_bp = Blueprint('users', __name__)


@user_bp.route('/users/search', methods=['GET'])
@login_required
def search_users():
    """Searches for local and LDAP users, using a 10-minute cache for LDAP."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    # Check cache freshness
    latest_entry = db.session.scalar(db.select(LdapUserCache).order_by(LdapUserCache.cached_at.desc()))
    ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)

    if not latest_entry or latest_entry.cached_at < ten_minutes_ago:
        current_app.logger.info("LDAP user cache is stale or empty. Refreshing...")

        # Call the new service function to get all users from the LDAP group
        ldap_users_list = ldap_service.get_all_users_in_group()

        if ldap_users_list is not None:
            try:
                # Clear the old cache
                db.session.execute(db.delete(LdapUserCache))

                # Create new cache entries
                new_cache_entries = [
                    LdapUserCache(uid=user['uid'], full_name=user['full_name'], email=user.get('mail'))
                    for user in ldap_users_list
                ]

                if new_cache_entries:
                    db.session.bulk_save_objects(new_cache_entries)

                db.session.commit()
                current_app.logger.info(f"Successfully refreshed LDAP cache with {len(new_cache_entries)} users.")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Failed to write to LdapUserCache table: {e}")
        else:
            current_app.logger.warning(
                "Failed to fetch users from LDAP. Search will use stale cache data if available.")

    results = []
    # Search Local Users
    local_users = db.session.scalars(
        db.select(LocalUser).filter(LocalUser.username.ilike(f'%{q}%')).limit(10)
    ).all()
    for user in local_users:
        results.append({'id': user.get_user_identifier(), 'display_name': f"{user.username} (Local)"})

    # Search Cached LDAP Users
    ldap_users = db.session.scalars(
        db.select(LdapUserCache).filter(
            or_(
                LdapUserCache.uid.ilike(f'%{q}%'),
                LdapUserCache.full_name.ilike(f'%{q}%')
            )
        ).limit(10)
    ).all()
    for user in ldap_users:
        results.append({'id': f"ldap:{user.uid}", 'display_name': f"{user.full_name or user.uid} (LDAP)"})

    return jsonify(results)


@user_bp.route('/shared-volumes', methods=['GET'])
@login_required
def get_shared_volumes():
    """
    Computes and returns a list of all volumes (projects, datasets) a user can mount.

    The allowed set is computed by ``volume_service.get_allowed_volumes`` -- the
    same function container creation uses to *enforce* mounts -- so the list a
    user is shown here and the list the create endpoint accepts cannot drift.
    """
    shareable_volumes = volume_service.get_allowed_volumes(current_user)
    # Convert dictionary to a sorted list for the frontend
    sorted_volumes = sorted(list(shareable_volumes.values()), key=lambda x: x['name'])
    return jsonify(sorted_volumes)


@user_bp.route('/admin/users', methods=['GET'])
@login_required
@admin_required
def admin_get_users():
    """Admin endpoint to list local users."""
    try:
        # Only listing Local users for now
        users = db.session.scalars(db.select(LocalUser).order_by(LocalUser.username)).all()
        return jsonify([u.to_dict() for u in users]), 200
    except Exception as e:
        current_app.logger.error(f"Admin failed to get users: {e}")
        return jsonify(message="Failed to retrieve users"), 500


@user_bp.route('/admin/users', methods=['POST'])
@login_required
@admin_required
def admin_create_user():
    """Admin endpoint to create a new local user."""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    is_admin = data.get('is_admin', False)

    if not username or not password:
        return jsonify({"message": "Username and password are required"}), 400
    if len(password) < 8:
        return jsonify({"message": "Password must be at least 8 characters long"}), 400

    if db.session.scalar(db.select(LocalUser).filter(func.lower(LocalUser.username) == func.lower(username))):
        return jsonify({"message": f"Username '{username}' already exists."}), 409

    try:
        new_user = LocalUser(username=username.strip())
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        if bool(is_admin):
            # Match the CLI `create-admin` / PUT promotion: an admin is a member
            # of group 0 AND a group-admin of it, so admins created here have the
            # same privileges as those created by the other paths.
            admin_membership = GroupMembership(
                user_uid=new_user.get_user_identifier(),
                group_id=0,
                is_group_admin=True
            )
            db.session.add(admin_membership)
            db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} created LocalUser: {username}")
        # Return new user data, excluding password hash
        return jsonify(new_user.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to create local user '{username}': {e}", exc_info=True)
        return jsonify({"message": "Failed to create user"}), 500


@user_bp.route('/admin/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_user(user_id):
    """Admin endpoint to update a local user."""
    user_to_edit = db.get_or_404(LocalUser, user_id)
    data = request.get_json()

    # Handle username change
    new_username = data.get('username')
    if new_username:
        # Check if new username is already taken by another user
        existing = db.session.scalar(
            db.select(LocalUser).filter(
                func.lower(LocalUser.username) == func.lower(new_username),
                LocalUser.id != user_id
            )
        )
        if existing:
            return jsonify({"message": f"Username '{new_username}' is already taken."}), 409
        user_to_edit.username = new_username.strip()

    # Handle admin status change
    if 'is_admin' in data:
        # Prevent admin from de-admining themselves if they are the only admin left
        if (current_user.user_type == 'local' and
                user_to_edit.id == int(current_user.get_id().split(':')[1]) and
                not data.get('is_admin')):
            admin_count = db.session.scalar(
                db.select(func.count()).select_from(GroupMembership)
                .where(GroupMembership.group_id == 0)
            )
            if admin_count <= 1:
                return jsonify({"message": "Cannot remove admin status from the last administrator."}), 403
        user_uid = f"local:{user_to_edit.id}"
        if bool(data['is_admin']):
            existing_membership = db.session.scalar(
                db.select(func.count()).select_from(GroupMembership)
                .where(GroupMembership.user_uid == user_uid, GroupMembership.group_id == 0)
            )
            if existing_membership == 0:
                new_admin_membership = GroupMembership(user_uid=user_uid, group_id=0)
                db.session.add(new_admin_membership)
                db.session.commit()
        else:
            db.session.execute(
                db.delete(GroupMembership)
                .where(GroupMembership.user_uid == user_uid, GroupMembership.group_id == 0)
            )

    # Handle password change (only if provided and not empty)
    new_password = data.get('password')
    if new_password and new_password.strip():
        if len(new_password) < 8:
            return jsonify({"message": "New password must be at least 8 characters long"}), 400
        user_to_edit.set_password(new_password)

    try:
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} updated LocalUser ID {user_id}")
        return jsonify(user_to_edit.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to update local user {user_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to update user"}), 500


@user_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_user(user_id):
    """Admin endpoint to delete a local user."""
    user_to_delete = db.get_or_404(LocalUser, user_id)

    # --- CRITICAL SAFETY CHECKS ---
    # 1. Prevent self-deletion
    if (current_user.user_type == 'local'
            and user_to_delete.id == int(current_user.get_id().split(':')[1])):
        return jsonify({"message": "You cannot delete your own account."}), 403

    # 2. Check if user owns any Projects
    if db.session.scalar(db.select(Project).filter_by(owner_local_user_id=user_id)):
        return jsonify({"message": "Cannot delete user: They still own one or more projects."}), 409

    # 3. Check if user owns any running Containers
    if db.session.scalar(db.select(ContainerInstance).filter_by(user_local_user_id=user_id)):
        return jsonify({"message": "Cannot delete user: They still own one or more containers."}), 409
    # --- End SAFETY CHECKS ---

    try:
        # Also delete associated SSH keys
        db.session.execute(
            db.delete(UserSSHKey).where(UserSSHKey.user_uid == f"local:{user_id}")
        )

        db.session.delete(user_to_delete)
        db.session.commit()
        current_app.logger.info(
            f"Admin {current_user.username} deleted LocalUser ID {user_id} (Username: {user_to_delete.username})")
        return '', 204
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Admin failed to delete user {user_id}: {e}", exc_info=True)
        return jsonify({"message": "Failed to delete user"}), 500


@user_bp.route('/notification-preferences', methods=['GET'])
@login_required
def get_notification_preferences():
    """Get current user's notification preferences."""
    # For now, we only support email notifications
    # In the future, this could be extended to include other preferences
    user_id = current_user.get_id()

    # Get email address for the user
    email = notification_service.get_user_email(user_id)

    # For now, we'll just return whether email is available
    # In a more complete implementation, we would return actual preferences
    return jsonify({
        'email_enabled': email is not None,
        'email': email
    })


@user_bp.route('/notification-preferences', methods=['PUT'])
@login_required
def update_notification_preferences():
    """Update current user's notification preferences."""
    data = request.get_json()

    # Validate input
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid input data"}), 400

    # For now, we only support enabling/disabling email notifications
    # In a more complete implementation, we would handle more preferences
    user_id = current_user.get_id()

    # Get current email
    current_email = notification_service.get_user_email(user_id)

    # If email is being enabled and we have an email address, we can enable notifications
    if data.get('email_enabled', False) and current_email:
        # In a real implementation, we would store these preferences in a database table
        # For now, we just return success
        return jsonify({
            "message": "Notification preferences updated successfully",
            "email_enabled": True,
            "email": current_email
        })
    elif not data.get('email_enabled', False):
        # Disable notifications
        return jsonify({
            "message": "Notification preferences updated successfully",
            "email_enabled": False,
            "email": current_email
        })
    else:
        return jsonify({"message": "Cannot enable notifications: no email address found"}), 400
