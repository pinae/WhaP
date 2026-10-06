from flask import Blueprint, request, jsonify, current_app
from flask_login import login_user, logout_user, current_user, login_required
from ..services import ldap_service, notification_service
from ..user_management import LocalUserWrapper, LdapUserWrapper
from ..models import LocalUser

bp = Blueprint('auth', __name__)

@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"message": "Username and password required"}), 400

    user_obj = None
    auth_method = None

    # --- 1. Try Local Database Authentication ---
    local_user = LocalUser.query.filter_by(username=username).first()
    if local_user:
        if local_user.check_password(password):
            user_obj = LocalUserWrapper(local_user)  # Pass the DB object
            auth_method = "local"
            current_app.logger.info(f"Local login successful for user {username}")
        else:
            current_app.logger.warning(f"Local login failed (password mismatch) for user {username}.")
            return jsonify({"message": "Invalid credentials"}), 401

    # --- 2. Try LDAP Authentication ---
    if not user_obj:
        current_app.logger.debug(f"User '{username}' not found locally or auth pending, trying LDAP...")
        ldap_details = ldap_service.authenticate_user(username, password)
        if ldap_details:
            user_obj = LdapUserWrapper(ldap_details)
            auth_method = "ldap"
            current_app.logger.info(f"LDAP login successful for user {username} (UID: {ldap_details['uid']})")
        else:
            # LDAP auth failed
            current_app.logger.warning(f"LDAP authentication failed for user {username}.")
            # If we got here, both local and LDAP failed
            return jsonify({"message": "Invalid credentials"}), 401

    # --- Login Success ---
    if user_obj and auth_method:
        login_user(user_obj) # Creates the session, stores the prefixed user ID
        current_app.logger.info(f"User {username} logged in successfully via {auth_method}.")
        
        # Get user's email address if available
        user_id = user_obj.get_id()
        email = notification_service.get_user_email(user_id)
        
        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user_obj.get_id(), # Prefixed ID (e.g., "local:1", "ldap:jdoe")
                "username": user_obj.username, # Actual username/uid
                "user_type": user_obj.user_type,
                "is_admin": user_obj.is_admin,
                "email": email
            }
        }), 200
    else:
        # Should not be reached if logic above is correct, but as a fallback
        current_app.logger.error(f"Login logic error for user {username}. No user object created.")
        return jsonify({"message": "An internal error occurred during login."}), 500


@bp.route('/logout', methods=['POST'])
@login_required # Ensures only logged-in users can call this
def logout():
    user_id = current_user.get_id() # Get ID for logging before logout
    logout_user()
    current_app.logger.info(f"User {user_id} logged out.")
    return jsonify({"message": "Logout successful"}), 200

@bp.route('/session', methods=['GET'])
def get_session():
    if current_user.is_authenticated:
        return jsonify({
            "isLoggedIn": True,
            "user": {
                 "id": current_user.get_id(), # Prefixed ID
                 "username": current_user.username,
                 "user_type": current_user.user_type,
                 "is_admin": current_user.is_admin
            }
        }), 200
    else:
        return jsonify({"isLoggedIn": False, "user": None}), 200
