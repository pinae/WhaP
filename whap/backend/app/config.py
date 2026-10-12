import os
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

# Load .env file from the directory where config.py is located or parent directories
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')  # Assumes .env is in backend/
if not os.path.exists(dotenv_path):
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')  # Check project root

load_dotenv(dotenv_path=dotenv_path, verbose=True)
print(f"Loading .env from: {dotenv_path}")

# The SECRET_KEY placeholder that used to be hard-coded as a fallback. Booting
# with it (or with no key at all) is refused by check_critical_config: a
# predictable key lets an attacker forge session cookies -> account/admin
# takeover.
INSECURE_SECRET_KEY = 'a-very-secretive-secret-key-please-change'

# Valid LDAP_TLS_OPTION values. Each maps onto python-ldap's OPT_X_TLS_<value>.
LDAP_TLS_OPTIONS = ('DEMAND', 'ALLOW', 'NEVER')

# Valid SMTP_SECURITY values: STARTTLS on a plain connection (port 587), TLS
# from the start (465), or none (a relay on the local network).
SMTP_SECURITY_OPTIONS = ('starttls', 'ssl', 'none')


def reminder_days(value):
    """TTL_REMINDER_DAYS ("7,1") as days before the ttl date, furthest first.

    Raises ValueError for anything but a list of positive whole numbers.
    """
    days = sorted({int(part) for part in str(value).split(',') if part.strip()}, reverse=True)
    if not days or days[-1] < 1:
        raise ValueError(value)
    return days


def _setting(cfg, name):
    """A setting from the Config class or from a Flask app's config (a dict)."""
    return cfg.get(name) if isinstance(cfg, dict) else getattr(cfg, name, None)


def email_configured(cfg):
    return bool(_setting(cfg, 'SMTP_SERVER') and _setting(cfg, 'SENDER_EMAIL'))


def matrix_configured(cfg):
    return bool(_setting(cfg, 'MATRIX_HOMESERVER_URL') and _setting(cfg, 'MATRIX_ACCESS_TOKEN'))


def roles_dirs(roles_path):
    """The directories in ANSIBLE_ROLES_PATH that exist, in Ansible's search order.

    The path is colon-separated, as Ansible reads it: the whap role sets
    /backend/roles[:/backend/roles_extra/N...]:/backend/roles_public.
    """
    return [d for d in (roles_path or '').split(os.pathsep) if d and os.path.isdir(d)]


def _runner_dir():
    """Where generated playbooks and ansible-runner's per-job data go.

    ANSIBLE_RUNNER_DIR if set, else <ANSIBLE_PROJECT_DIR>/ansible_runner -- the
    path always used before the setting was read. Absolute, because
    ansible-runner changes directory.
    """
    if os.environ.get('ANSIBLE_RUNNER_DIR'):
        return os.path.abspath(os.environ['ANSIBLE_RUNNER_DIR'])
    if os.environ.get('ANSIBLE_PROJECT_DIR'):
        return os.path.join(os.path.abspath(os.environ['ANSIBLE_PROJECT_DIR']), 'ansible_runner')
    return None


class Config:
    # --- Core Flask Settings ---
    # Mandatory: no in-source fallback. check_critical_config() fails fast if
    # this is unset or left at the known-insecure placeholder.
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # --- Database ---
    # Default to PostgreSQL on localhost if DATABASE_URL not set
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'postgresql://user:password@localhost/mydockerappdb'  # CHANGE DEFAULTS
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'False').lower() == 'true'  # Log SQL statements if True

    REDIS_HOST = os.environ.get('REDIS_HOST') or 'localhost'
    REDIS_PORT = os.environ.get('REDIS_PORT') or '6379'

    PROJECT_STORAGE_DIR = os.environ.get('PROJECT_STORAGE_DIR', '/data')
    LOCAL_BASE_PATH = os.environ.get('LOCAL_BASE_PATH', '/home')
    # Base path for globally shared datasets
    DATASETS_BASE_PATH = os.environ.get('DATASETS_BASE_PATH', '/data/DATASETS')
    DATASETS_LOCAL_BASE_PATH = os.environ.get('DATASETS_LOCAL_BASE_PATH', '/home/DATASETS')
    DOCS_DIR = os.environ.get('DOCS_DIR', '/backend/docs')

    DOCKER_REGISTRY = os.environ.get("DOCKER_REGISTRY", "")

    # Marks a test rig. `flask e2e-seed` and `flask e2e-reset` refuse to run
    # without it: reset deletes users' projects and their directories.
    E2E_FIXTURES_ENABLED = os.environ.get('E2E_FIXTURES_ENABLED', 'False').lower() == 'true'
    CONTAINER_FILE_OWNER = os.environ.get("CONTAINER_FILE_OWNER", "pina")

    # --- LDAP Configuration - CRITICAL ---
    LDAP_SERVER_URI = os.environ.get('LDAP_SERVER_URI')  # e.g., "ldaps://ldap.ruhr-uni-bochum.de:636"
    # Base DN where user accounts are located
    LDAP_USER_BASE_DN = os.environ.get('LDAP_USER_BASE_DN')  # e.g., "ou=people,dc=ruhr-uni-bochum,dc=de"
    # Optional: Service account for searching if anonymous search is disabled or direct DNs fail
    LDAP_BIND_USER = os.environ.get('LDAP_BIND_USER')  # Full DN of service account
    LDAP_BIND_PASSWORD = os.environ.get('LDAP_BIND_PASSWORD')  # Password for service account
    # Certificate verification for ldaps:// connections -- one of LDAP_TLS_OPTIONS.
    # It does not switch TLS on or off; the URI scheme does (ldap:// is plaintext).
    #   DEMAND  verify the server certificate, refuse on failure
    #   ALLOW   verify, but continue if the certificate is bad
    #   NEVER   do not check the certificate at all
    # Default to DEMAND: ALLOW and NEVER accept invalid/self-signed certs,
    # exposing the bind password (and user credentials) to a MITM.
    LDAP_TLS_OPTION = os.environ.get('LDAP_TLS_OPTION', 'DEMAND')
    # Optional: CA certificate to verify the server against, e.g. a private CA.
    LDAP_CA_CERT_FILE = os.environ.get('LDAP_CA_CERT_FILE')
    # objectClass of person entries listed by the user search. Site-specific:
    # RUB's directory uses rubPerson; a stock OpenLDAP uses inetOrgPerson.
    LDAP_USER_OBJECT_CLASS = os.environ.get('LDAP_USER_OBJECT_CLASS', 'rubPerson')

    # --- Ansible Runner ---
    # Directory to store ansible-runner artifacts (playbooks, logs, inventory)
    # Ensure this directory is writable by the user running the Flask app.
    ANSIBLE_CONTAINER_BASE_DIR = os.environ.get('ANSIBLE_CONTAINER_BASE_DIR')
    # Path where Ansible should look for roles (e.g., cloned git repo, system path)
    # CRITICAL: Make sure this path contains the roles referenced by DockerImage models
    ANSIBLE_ROLES_PATH = os.environ.get('ANSIBLE_ROLES_PATH')
    # Set Ansible Runner verbosity (True hides most Ansible output)
    ANSIBLE_SSH_PRIVATE_KEY_FILE = os.environ.get('ANSIBLE_SSH_PRIVATE_KEY_FILE')
    ANSIBLE_PROJECT_DIR = os.environ.get('ANSIBLE_PROJECT_DIR')
    ANSIBLE_RUNNER_DIR = _runner_dir()

    # --- Notifications ---
    # WhaP's address as users reach it, for links in notifications.
    WHAP_URL = os.environ.get('WHAP_URL', '')
    # Email. Without SMTP_SERVER and SENDER_EMAIL, WhaP sends no email.
    SMTP_SERVER = os.environ.get('SMTP_SERVER')
    SMTP_PORT = os.environ.get('SMTP_PORT', '587')
    SMTP_SECURITY = os.environ.get('SMTP_SECURITY', 'starttls').lower()  # one of SMTP_SECURITY_OPTIONS
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME')  # optional: a relay may not need a login
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
    SENDER_NAME = os.environ.get('SENDER_NAME', 'WhaP')
    # Matrix. The bot account WhaP sends as: its homeserver and an access token.
    # Without both, users cannot connect a Matrix account.
    MATRIX_HOMESERVER_URL = os.environ.get('MATRIX_HOMESERVER_URL', '').rstrip('/')
    MATRIX_ACCESS_TOKEN = os.environ.get('MATRIX_ACCESS_TOKEN')
    # Optional: the part after the colon in users' Matrix IDs, e.g. "example.org".
    # LDAP users' settings then start with "@<uid>:example.org" filled in.
    MATRIX_USER_DOMAIN = os.environ.get('MATRIX_USER_DOMAIN', '')
    # Days before a local container's ttl date that its owner is reminded.
    TTL_REMINDER_DAYS = os.environ.get('TTL_REMINDER_DAYS', '7,1')
    # Times in notifications are shown in this zone, e.g. "Europe/Berlin".
    TIMEZONE = os.environ.get('TIMEZONE', 'UTC')

    # --- CORS ---
    # Comma-separated list of allowed frontend origins. Use specific URLs in production!
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://localhost:3000')

    # --- Session Cookie Settings ---
    # Secure by default; override per-environment via env vars. Tests run over
    # plain HTTP and set SESSION_COOKIE_SECURE = False in their config.
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'True').lower() == 'true'  # Require HTTPS
    SESSION_COOKIE_HTTPONLY = os.environ.get('SESSION_COOKIE_HTTPONLY',
                                             'True').lower() == 'true'  # No client-side JS access
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')  # CSRF protection ('Strict' or 'Lax')
    PERMANENT_SESSION_LIFETIME = int(os.environ.get('PERMANENT_SESSION_LIFETIME', 3600 * 8))  # 8 hours


# --- Security validation ---------------------------------------------------
def find_config_problems(cfg):
    """Return a list of security problems with ``cfg`` (empty == OK).

    Pure and side-effect-free so it can be unit-tested with throwaway config
    objects. ``check_critical_config`` layers presence/filesystem checks on top.
    """
    problems = []

    secret = getattr(cfg, 'SECRET_KEY', None)
    if not secret:
        problems.append("SECRET_KEY is not set. Set a strong, random value.")
    elif secret == INSECURE_SECRET_KEY:
        problems.append("SECRET_KEY is the known-insecure placeholder. Set a strong, random value.")

    # Credentialed CORS with a '*' origin is unsafe (and rejected by browsers);
    # require explicit origins.
    cors = getattr(cfg, 'CORS_ORIGINS', '') or ''
    if '*' in [origin.strip() for origin in cors.split(',')]:
        problems.append("CORS_ORIGINS must list explicit origins, not '*', when credentials are allowed.")

    # An unrecognised value used to fall through silently and leave whatever
    # certificate check the process last used; refuse to boot instead.
    tls_option = (getattr(cfg, 'LDAP_TLS_OPTION', None) or 'DEMAND').upper()
    if tls_option not in LDAP_TLS_OPTIONS:
        problems.append(f"LDAP_TLS_OPTION must be one of {', '.join(LDAP_TLS_OPTIONS)}, got '{tls_option}'.")

    problems.extend(_notification_problems(cfg))
    return problems


def _notification_problems(cfg):
    problems = []
    if (getattr(cfg, 'SMTP_SECURITY', None) or 'starttls') not in SMTP_SECURITY_OPTIONS:
        problems.append(f"SMTP_SECURITY must be one of {', '.join(SMTP_SECURITY_OPTIONS)}, "
                        f"got '{cfg.SMTP_SECURITY}'.")
    port = str(getattr(cfg, 'SMTP_PORT', None) or '587')
    if not port.isdigit() or not 0 < int(port) < 65536:
        problems.append(f"SMTP_PORT must be a port number, got '{port}'.")
    if bool(getattr(cfg, 'SMTP_SERVER', None)) != bool(getattr(cfg, 'SENDER_EMAIL', None)):
        problems.append("Set SMTP_SERVER and SENDER_EMAIL together (or neither, to send no email).")
    if bool(getattr(cfg, 'SMTP_USERNAME', None)) != bool(getattr(cfg, 'SMTP_PASSWORD', None)):
        problems.append("Set SMTP_USERNAME and SMTP_PASSWORD together (or neither, for a relay without login).")

    homeserver = getattr(cfg, 'MATRIX_HOMESERVER_URL', None) or ''
    if bool(homeserver) != bool(getattr(cfg, 'MATRIX_ACCESS_TOKEN', None)):
        problems.append("Set MATRIX_HOMESERVER_URL and MATRIX_ACCESS_TOKEN together "
                        "(or neither, to offer no Matrix).")
    elif homeserver and not homeserver.startswith('https://'):
        # The access token goes with every request; over http it is readable on the way.
        problems.append(f"MATRIX_HOMESERVER_URL must be an https:// address, got '{homeserver}'.")

    whap_url = getattr(cfg, 'WHAP_URL', None) or ''
    if whap_url and not whap_url.startswith(('https://', 'http://')):
        problems.append(f"WHAP_URL must start with https:// or http://, got '{whap_url}'.")

    timezone_name = getattr(cfg, 'TIMEZONE', None) or 'UTC'
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        problems.append(f"TIMEZONE must be a time zone name such as 'Europe/Berlin', got '{timezone_name}'.")

    try:
        reminder_days(getattr(cfg, 'TTL_REMINDER_DAYS', None) or '7,1')
    except ValueError:
        problems.append("TTL_REMINDER_DAYS must list whole numbers of days, e.g. '7,1', "
                        f"got '{cfg.TTL_REMINDER_DAYS}'.")
    return problems


def notification_channels_report(cfg):
    """One line per channel saying whether WhaP can use it."""
    lines = []
    if email_configured(cfg):
        lines.append(f"OK: email notifications via {cfg.SMTP_SERVER}:{cfg.SMTP_PORT} from {cfg.SENDER_EMAIL}")
    else:
        lines.append("WARNING: email notifications are off: SMTP_SERVER and SENDER_EMAIL are not set.")
    if matrix_configured(cfg):
        lines.append(f"OK: Matrix notifications via {cfg.MATRIX_HOMESERVER_URL}")
    else:
        lines.append("OK: Matrix notifications are off (MATRIX_HOMESERVER_URL not set).")
    if not getattr(cfg, 'WHAP_URL', None):
        lines.append("WARNING: WHAP_URL is not set; notifications will contain no links to WhaP.")
    return lines


# --- Helper Function to Check Config ---
def check_critical_config():
    print("Checking critical configuration...")
    is_ok = True

    cfg = Config()

    # Security problems (secret key, CORS) are always fatal.
    security_problems = find_config_problems(cfg)
    for problem in security_problems:
        print(f"  ERROR: {problem}")
    if security_problems:
        is_ok = False

    # Presence checks for operationally-required settings. SECRET_KEY is handled
    # by find_config_problems above, so it is not repeated here.
    critical_vars = [
        'SQLALCHEMY_DATABASE_URI',
        'REDIS_HOST',
        'REDIS_PORT',
        'LDAP_SERVER_URI',
        'LDAP_USER_BASE_DN',
        'ANSIBLE_ROLES_PATH',
        'ANSIBLE_PROJECT_DIR',
        'ANSIBLE_CONTAINER_BASE_DIR'
    ]
    for var in critical_vars:
        value = getattr(cfg, var, None)
        if not value:
            print(f"  ERROR: Critical config variable '{var}' is not set!")
            is_ok = False
        else:
            # Avoid printing secrets directly in logs
            display_value = value if var not in ['LDAP_BIND_PASSWORD'] else '******'
            print(f"  OK: {var} = {display_value}")

    # Colon-separated, like Ansible's own setting; checking it as one path
    # failed every deployment with more than one roles directory.
    if not roles_dirs(cfg.ANSIBLE_ROLES_PATH):
        print(f"  ERROR: ANSIBLE_ROLES_PATH '{cfg.ANSIBLE_ROLES_PATH}' names no existing directory.")
        is_ok = False
    else:
        for missing in set((cfg.ANSIBLE_ROLES_PATH or '').split(os.pathsep)) - set(roles_dirs(cfg.ANSIBLE_ROLES_PATH)):
            if missing:
                print(f"  WARNING: ANSIBLE_ROLES_PATH entry '{missing}' does not exist.")

    for line in notification_channels_report(cfg):
        print(f"  {line}")

    if not is_ok:
        print(
            "\nFATAL: Critical configuration missing or insecure. Please set environment variables or update .env file.")
        # 3 is gunicorn's "worker failed to boot": the master stops and the
        # container restarts visibly. With 1, gunicorn respawns the worker
        # forever and the backend silently hangs every request.
        sys.exit(3)
    else:
        print("Critical configuration check passed.")
