"""A user's own notification settings: channels, topics, connecting Matrix, a test message.

A change that leaves WhaP unable to warn the user before their containers are
stopped or their local data deleted -- no channel that reaches them, or both
data-protecting topics off -- is refused with 409 until the request says
``acknowledge_risk: true``. The time of that acknowledgement is kept.
"""
import re
import secrets
from datetime import datetime, timedelta, UTC

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db
from ..config import email_configured, matrix_configured, reminder_days
from ..models import NOTIFICATION_TOPICS, NotificationSettings, _iso_utc
from ..notifications import dispatch, render
from ..notifications.errors import DeliveryError
from ..notifications.matrix_channel import MatrixChannel

nset_bp = Blueprint('notification_settings', __name__)

MATRIX_ID = re.compile(r'^@[^:\s]+:[A-Za-z0-9.\-]+(:[0-9]+)?$')
CODE_VALID_FOR = timedelta(minutes=15)
CODE_RESEND_AFTER = timedelta(seconds=60)
CODE_MAX_ATTEMPTS = 5


def _now():
    return datetime.now(UTC)


def _aware(value):
    # SQLite gives naive datetimes back; they are stored as UTC.
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _settings():
    """The current user's saved settings, created (unsaved) if they have none yet."""
    uid = current_user.get_id()
    settings = db.session.get(NotificationSettings, uid)
    if settings is None:
        settings = NotificationSettings(user_uid=uid)
        db.session.add(settings)
    return settings


def _reachable(settings, email):
    """The channels that would actually reach this user."""
    config = current_app.config
    channels = []
    if settings.email_enabled and email and email_configured(config):
        channels.append('email')
    if 'matrix' in settings.channels() and matrix_configured(config):
        channels.append('matrix')
    return channels


def _protected(settings, email):
    return bool(_reachable(settings, email)) and (settings.topic_maintenance or settings.topic_expiry)


def _suggested_matrix_id():
    """@<LDAP uid>:<MATRIX_USER_DOMAIN>: on a university homeserver, the ID a user most likely has."""
    domain = (current_app.config.get('MATRIX_USER_DOMAIN') or '').strip().lstrip('@:')
    if domain and current_user.user_type == 'ldap':
        # Matrix user IDs are lower case.
        return f"@{current_user.username.lower()}:{domain}"
    return None


def _view(settings, email):
    config = current_app.config
    try:
        days = reminder_days(config.get('TTL_REMINDER_DAYS') or '7,1')
    except ValueError:
        days = [7, 1]
    return {
        'email': {'enabled': settings.email_enabled, 'address': email, 'available': email_configured(config)},
        'matrix': {
            'available': matrix_configured(config),
            'enabled': settings.matrix_enabled,
            'id': settings.matrix_id,
            'pending_id': settings.matrix_pending_id,
            'suggestion': _suggested_matrix_id(),
        },
        'topics': {topic: getattr(settings, f'topic_{topic}') for topic in NOTIFICATION_TOPICS},
        'reminder_days': days,
        'reachable': _reachable(settings, email),
        'protects_data': _protected(settings, email),
        'risk_acknowledged_at': _iso_utc(settings.all_off_acknowledged_at),
    }


def _commit_unless_risky(settings, email, was_protected):
    """Commit, unless the change stops WhaP warning the user and they haven't said they accept that."""
    if was_protected and not _protected(settings, email):
        if not (request.get_json(silent=True) or {}).get('acknowledge_risk'):
            reachable = _reachable(settings, email)
            db.session.rollback()
            return jsonify({
                'message': "WhaP could no longer warn you before your containers are stopped "
                           "or your local data is deleted.",
                'needs_acknowledgement': True,
                'all_off': not reachable,
            }), 409
        settings.all_off_acknowledged_at = _now()
    elif _protected(settings, email):
        settings.all_off_acknowledged_at = None
    db.session.commit()
    return jsonify(_view(settings, email)), 200


@nset_bp.route('/notification-settings', methods=['GET'])
@login_required
def get_settings():
    settings = NotificationSettings.for_user(current_user.get_id())
    return jsonify(_view(settings, current_user.email))


@nset_bp.route('/notification-settings', methods=['PUT'])
@login_required
def update_settings():
    """Change any of: email_enabled, matrix_enabled, topics {name: bool}."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'message': 'Send the settings to change as JSON.'}), 400
    topics = data.get('topics', {})
    if not isinstance(topics, dict) or set(topics) - set(NOTIFICATION_TOPICS):
        return jsonify({'message': f"Topics are {', '.join(NOTIFICATION_TOPICS)}."}), 400
    if any(not isinstance(v, bool) for v in [*topics.values(), *(data[k] for k in
                                                                    ('email_enabled', 'matrix_enabled') if k in data)]):
        return jsonify({'message': 'Switches are true or false.'}), 400

    email = current_user.email
    settings = _settings()
    was_protected = _protected(settings, email)
    if 'email_enabled' in data:
        settings.email_enabled = data['email_enabled']
    if 'matrix_enabled' in data:
        if data['matrix_enabled'] and not settings.matrix_id:
            db.session.rollback()
            return jsonify({'message': 'Connect a Matrix account first.'}), 400
        settings.matrix_enabled = data['matrix_enabled']
    for topic, on in topics.items():
        setattr(settings, f'topic_{topic}', on)
    return _commit_unless_risky(settings, email, was_protected)


# --- Matrix --------------------------------------------------------------------

def _send_code(settings, matrix_id):
    channel = MatrixChannel(current_app.config)
    room = settings.matrix_pending_room_id if settings.matrix_pending_id == matrix_id else None
    if not room:
        room = channel.create_direct_room(matrix_id)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    channel.send(room, f"Your WhaP code: {code}\n\nEnter it in WhaP's settings to connect this Matrix account. "
                       f"It expires in {CODE_VALID_FOR.seconds // 60} minutes. "
                       "If you didn't ask for it, ignore this message.",
                 txn_id=f"whap-code-{secrets.token_hex(8)}")
    settings.matrix_pending_id = matrix_id
    settings.matrix_pending_room_id = room
    settings.matrix_code_hash = generate_password_hash(code)
    settings.matrix_code_expires_at = _now() + CODE_VALID_FOR
    settings.matrix_code_attempts = 0


@nset_bp.route('/notification-settings/matrix', methods=['POST'])
@login_required
def connect_matrix():
    """Start connecting {matrix_id}: the bot invites them to a chat and sends a code."""
    if not matrix_configured(current_app.config):
        return jsonify({'message': 'This WhaP has no Matrix bot.'}), 400
    matrix_id = ((request.get_json(silent=True) or {}).get('matrix_id') or '').strip()
    if len(matrix_id) > 255 or not MATRIX_ID.match(matrix_id):
        return jsonify({'message': f"'{matrix_id}' is not a Matrix ID like @alice:matrix.example.org."}), 400

    settings = _settings()
    expires = _aware(settings.matrix_code_expires_at)
    if (settings.matrix_pending_id == matrix_id and expires
            and expires - CODE_VALID_FOR + CODE_RESEND_AFTER > _now()):
        db.session.rollback()
        return jsonify({'message': 'A code was sent less than a minute ago. Check the chat with WhaP.'}), 429
    try:
        _send_code(settings, matrix_id)
    except DeliveryError as e:
        db.session.rollback()
        current_app.logger.warning(f"Matrix code for {current_user.get_id()} to {matrix_id} failed: {e}")
        return jsonify({'message': f"WhaP's bot could not write to {matrix_id}: {e}"}), 502
    db.session.commit()
    return jsonify(_view(settings, current_user.email)), 200


@nset_bp.route('/notification-settings/matrix/verify', methods=['POST'])
@login_required
def verify_matrix():
    code = str((request.get_json(silent=True) or {}).get('code') or '').strip()
    settings = _settings()
    expires = _aware(settings.matrix_code_expires_at)
    if not settings.matrix_pending_id or not settings.matrix_code_hash:
        db.session.rollback()
        return jsonify({'message': 'No code is waiting. Connect a Matrix account first.'}), 400
    if expires is None or expires < _now():
        return jsonify({'message': 'The code has expired. Send a new one.'}), 400
    if not check_password_hash(settings.matrix_code_hash, code):
        settings.matrix_code_attempts += 1
        if settings.matrix_code_attempts >= CODE_MAX_ATTEMPTS:
            settings.matrix_code_hash = None
            db.session.commit()
            return jsonify({'message': 'Too many wrong codes. Send a new one.'}), 400
        db.session.commit()
        return jsonify({'message': 'That is not the code WhaP sent.'}), 400

    old_room = settings.matrix_room_id
    settings.matrix_id = settings.matrix_pending_id
    settings.matrix_room_id = settings.matrix_pending_room_id
    settings.matrix_enabled = True
    settings.matrix_pending_id = settings.matrix_pending_room_id = settings.matrix_code_hash = None
    settings.matrix_code_expires_at = None
    settings.matrix_code_attempts = 0
    email = current_user.email
    if _protected(settings, email):
        settings.all_off_acknowledged_at = None
    db.session.commit()
    if old_room and old_room != settings.matrix_room_id:
        _leave(old_room)  # the account it replaced
    return jsonify(_view(settings, email)), 200


@nset_bp.route('/notification-settings/matrix/pending', methods=['DELETE'])
@login_required
def cancel_matrix_code():
    settings = _settings()
    settings.matrix_pending_id = settings.matrix_pending_room_id = settings.matrix_code_hash = None
    settings.matrix_code_expires_at = None
    settings.matrix_code_attempts = 0
    db.session.commit()
    return jsonify(_view(settings, current_user.email)), 200


@nset_bp.route('/notification-settings/matrix', methods=['DELETE'])
@login_required
def disconnect_matrix():
    email = current_user.email
    settings = _settings()
    was_protected = _protected(settings, email)
    room = settings.matrix_room_id
    settings.matrix_id = settings.matrix_room_id = None
    settings.matrix_enabled = False
    response = _commit_unless_risky(settings, email, was_protected)
    if response[1] == 200 and room:
        _leave(room)
    return response


def _leave(room):
    try:
        MatrixChannel(current_app.config).leave(room)
    except DeliveryError as e:  # the chat stays; nothing more is sent to it
        current_app.logger.info(f"Bot could not leave {room}: {e}")


# --- test -----------------------------------------------------------------------

@nset_bp.route('/notification-settings/test', methods=['POST'])
@login_required
def send_test():
    """Send a test message on every channel that reaches the user; report each."""
    config = current_app.config
    email = current_user.email
    settings = NotificationSettings.for_user(current_user.get_id())
    whap_url = (config.get('WHAP_URL') or '').rstrip('/')
    text = ("This is a test from WhaP. If you can read it, notifications reach you here."
            + (f"\n\nChange what WhaP tells you: {whap_url}/settings" if whap_url else ""))
    results = dispatch.send_directly(email, settings, render.Message(
        subject="Test notification", text=text, html=render.text_to_html(text)))
    if not results:
        return jsonify({'message': 'No channel is switched on that reaches you.', 'results': []}), 400
    return jsonify({'results': results}), 200
