import os
import logging
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_cors import CORS
from flask_socketio import SocketIO
from .config import Config
from flask import jsonify
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

# --- App Extension Instances ---
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
# Default to "strong" in production; overridable via config. The Socket.IO test
# client performs a simulated handshake that may lack a stable User-Agent /
# remote address, which "strong" protection treats as a session change and
# clears. Tests set SESSION_PROTECTION = "basic" so the login session survives
# into the Socket.IO handlers; production keeps "strong".
login_manager.session_protection = "strong"

# Socket.IO uses a Redis message queue as a backplane so that emits from any
# process (web workers, the queue consumer) reach every connected client.
# SOCKETIO_MESSAGE_QUEUE overrides the URL; setting it to an empty string
# disables the backplane entirely (useful for tests and single-process dev).
_default_redis_url = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}"
redis_url = os.getenv("SOCKETIO_MESSAGE_QUEUE", _default_redis_url)
socketio = SocketIO(async_mode="threading", message_queue=(redis_url or None))


# --- App Factory Function ---
def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ProxyFix is needed to run the application behind a reverse proxy like Traefik
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

    # Standard initializations
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')
    app.logger.info("Flask app starting...")

    # Ensure Ansible Runner dir exists
    runner_dir = app.config.get('ANSIBLE_RUNNER_DIR')
    if runner_dir:
        try:
            os.makedirs(runner_dir, exist_ok=True)
            app.logger.info(f"Ansible runner directory set to: {runner_dir}")
        except OSError as e:
            app.logger.error(f"Could not create Ansible runner directory {runner_dir}: {e}")
    else:
        app.logger.warning("ANSIBLE_RUNNER_DIR not configured, defaulting might occur.")

    # --- Initialize Extensions with App ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.session_protection = app.config.get("SESSION_PROTECTION", "strong")
    cors_origins = app.config.get('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5000').split(',')
    CORS(app, supports_credentials=True, origins=cors_origins)
    # async_mode='threading' replaces eventlet (no monkey-patching, Python 3.13
    # safe). manage_session is left at its default (True): Flask-SocketIO seeds
    # each connection's session from the Flask login cookie at connect time, so
    # current_user still resolves in the handlers, but every connection gets its
    # OWN session snapshot. Do NOT set manage_session=False here -- that shares a
    # single Flask session across connections, so an authenticated handshake
    # leaks its identity into the next (anonymous) one and breaks the connect
    # rejection.
    socketio.init_app(app, async_mode='threading', cors_allowed_origins=cors_origins)

    # --- Import and Register Blueprints/Routes ---
    with app.app_context():
        # Import models so they are registered with SQLAlchemy
        from . import models
        # Import event handlers so they are registered with SocketIO
        from . import events
        # Import user management to register the user_loader
        from . import user_management

        from .routes.auth import bp as auth_bp
        app.register_blueprint(auth_bp, url_prefix='/auth')

        from .routes.api import bp as api_bp
        app.register_blueprint(api_bp, url_prefix='/api')

        app.logger.info("Blueprints registered.")

        # --- Define and Register CLI Commands ---
        @app.cli.command("create-admin")
        @click.option('--username', prompt=True, default='admin')
        @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
        def create_admin(username, password):
            from .models import LocalUser
            if db.session.scalar(db.select(LocalUser).filter_by(username=username)):
                print(f"Error: Username '{username}' already exists.")
                return
            admin_user = LocalUser(username=username)
            admin_user.set_password(password)
            db.session.add(admin_user)
            db.session.commit()

            # Add to Admin group (ID 0)
            from .models import Group, GroupMembership
            admin_group = db.session.get(Group, 0)
            if admin_group:
                admin_membership = GroupMembership(user_uid=f"local:{admin_user.id}", group_id=0, is_group_admin=True)
                db.session.add(admin_membership)
                db.session.commit()
                print(f"Admin user '{username}' created and added to Admins group.")
            else:
                print(f"Admin user '{username}' created, but Admin group (ID 0) not found. Please run migrations.")

        @app.cli.command("add-to-admin-group")
        @click.option('--username', prompt=True, help="The username of the user to add.")
        @click.option('--user-type', prompt=True, type=click.Choice(['local', 'ldap'], case_sensitive=False),
                      default='local', help="The type of user.")
        def add_to_admin_group(username, user_type):
            """Adds a local or LDAP user to the Admins group."""
            from .models import LocalUser, Group, GroupMembership

            user_uid = None
            if user_type.lower() == 'local':
                user = db.session.scalar(db.select(LocalUser).filter_by(username=username))
                if not user:
                    print(f"Error: Local user '{username}' not found.")
                    return
                user_uid = f"local:{user.id}"
            else:  # ldap
                user_uid = f"ldap:{username}"

            admin_group = db.session.get(Group, 0)
            if not admin_group:
                print("Error: Admin group (ID 0) not found. Please ensure migrations have been run correctly.")
                return

            existing_membership = db.session.scalar(db.select(GroupMembership).filter_by(user_uid=user_uid, group_id=0))
            if existing_membership:
                print(f"User '{username}' is already in the Admins group.")
                return

            new_membership = GroupMembership(user_uid=user_uid, group_id=0, is_group_admin=True)
            db.session.add(new_membership)
            db.session.commit()
            print(f"Successfully added {user_type} user '{username}' to the Admins group.")

        @app.cli.command("rename-projects")
        def rename_projects():
            """Renames all existing projects to their safe_project_name."""
            from .models import Project
            projects = Project.query.all()
            renamed_count = 0
            for project in projects:
                safe_name = "".join(c if c.isalnum() else "_" for c in project.name)
                if project.name != safe_name:
                    print(f"Renaming project '{project.name}' to '{safe_name}'")
                    project.name = safe_name
                    renamed_count += 1
            db.session.commit()
            print(f"Successfully renamed {renamed_count} projects.")

        return app


# --- Admin Required Decorator ---
@login_manager.unauthorized_handler
def unauthorized():
    return jsonify(message="Authentication required."), 401


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify(message="Administrator privileges required."), 403
        return f(*args, **kwargs)

    return decorated_function
