from flask import current_app
from flask_socketio import emit, join_room, leave_room, ConnectionRefusedError
from flask_login import current_user
from . import socketio, db  # shared instances from __init__.py
from .models import AnsibleJob, ContainerInstance
from .services import permissions_service
import re

# Matches the ANSI colour codes ansible emits, so replayed history looks like the
# live stream (run.py strips the same codes before sending live lines).
_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


@socketio.on('connect')
def handle_connect():
    """Handles new client connections.

    ``current_user`` resolves from the Flask-Login session carried on the
    Socket.IO handshake (the same cookie used for normal HTTP requests).
    Unauthenticated clients are rejected by raising ``ConnectionRefusedError``
    -- the canonical Flask-SocketIO mechanism. (Returning ``False`` also rejects
    a real connection, but the test client only treats a raised
    ``ConnectionRefusedError`` as a refusal, so this keeps behaviour identical
    in production and under test.)
    """
    if not current_user.is_authenticated:
        current_app.logger.warning('Unauthenticated user tried to connect to SocketIO. Rejecting.')
        raise ConnectionRefusedError('Authentication required.')

    current_app.logger.info(f'SocketIO Client connected: {current_user.get_id()}')
    emit('status', {'msg': 'Successfully connected to backend logs.'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handles client disconnections."""
    user_id = current_user.get_id() if current_user.is_authenticated else "Anonymous"
    current_app.logger.info(f'SocketIO Client disconnected: {user_id}')


def _log_lines_for_replay(log_text):
    """Split a stored job log into cleaned, non-empty lines (ANSI stripped),
    matching the per-line shape used for the live stream. Pure/testable."""
    cleaned = []
    for raw_line in (log_text or "").splitlines():
        line = _ANSI_ESCAPE.sub('', raw_line).rstrip()
        if line:
            cleaned.append(line)
    return cleaned


def _replay_saved_logs(container_id_str):
    """Re-send the most recent stored job log for a container to the client that
    just joined, so a reconnecting user (or one who reopened their browser) sees
    prior output instead of a blank view. Emitted only to the requesting client.

    A job's ``log`` is persisted when the job finishes, so this replays the full
    output of the latest completed run; an in-progress run's live lines still
    arrive over the room as usual.
    """
    try:
        container_id = int(container_id_str)
    except (TypeError, ValueError):
        return

    try:
        latest_job = db.session.scalar(
            db.select(AnsibleJob)
            .filter_by(container_instance_id=container_id)
            .order_by(AnsibleJob.created_at.desc())
        )
    except Exception as e:  # never let a history lookup break the join
        current_app.logger.warning(f"Could not load saved logs for container {container_id}: {e}")
        return

    if not latest_job:
        return

    for line in _log_lines_for_replay(latest_job.log):
        emit('ansible_log', {'container_id': container_id, 'line': line})


@socketio.on('join_log_room')
def handle_join_log_room(data):
    """Allows a client to join a room to receive logs for a specific container."""
    if not current_user.is_authenticated:
        current_app.logger.warning("Unauthenticated attempt to join log room.")
        return

    container_id_str = str(data.get('container_id'))
    # str(None) == 'None' (truthy), so guard the missing-id case explicitly.
    if not container_id_str or container_id_str == 'None':
        current_app.logger.warning("join_log_room event received without container_id.")
        return

    # Ownership check: logs show a container's addresses, paths and public key
    # (passwords are redacted), so only the owner (or an admin) may join its room.
    try:
        container = db.session.get(ContainerInstance, int(container_id_str))
    except (TypeError, ValueError):
        container = None
    if not permissions_service.user_can_access_container(current_user, container):
        current_app.logger.warning(
            f"User {current_user.get_id()} denied join to log room for container '{container_id_str}'."
        )
        return

    join_room(container_id_str)  # The room is named after the container_id
    current_app.logger.info(f"User {current_user.get_id()} joined SocketIO room for container '{container_id_str}'")
    emit('status', {'msg': f'Joined log room for container {container_id_str}.'}, room=container_id_str)
    # Replay stored history to just this client (reconnect / reopened browser).
    _replay_saved_logs(container_id_str)


@socketio.on('leave_log_room')
def handle_leave_log_room(data):
    """Allows a client to leave a container's log room."""
    if not current_user.is_authenticated:
        return

    container_id_str = str(data.get('container_id'))
    if container_id_str:
        leave_room(container_id_str)
        current_app.logger.info(f"User {current_user.get_id()} left SocketIO room for container '{container_id_str}'")
