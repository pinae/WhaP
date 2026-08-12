"""Socket.IO handler tests (threading async mode).

These assert the connect/join *handler logic* directly, via a request context,
rather than through the in-process flask_socketio test client. We verified by
probing that the test client is unreliable here for two independent reasons,
neither of which reflects production:

  * it leaks Flask-Login identity between successive connections in one process
    (a prior authenticated client makes the next "anonymous" one authenticated);
  * what it captures on connect depends on the manage_session mode.

Driving the handlers directly is deterministic, order-independent, and
indifferent to manage_session. ``manage_session`` stays at its default (True)
in app/__init__.py so that every Socket.IO connection gets its own session
snapshot (manage_session=False would share one session across all clients).
"""
import pytest

pytest.importorskip("flask_socketio")

from flask import session  # noqa: E402
from flask_socketio import ConnectionRefusedError  # noqa: E402
import app.events as events  # noqa: E402


def _login(user):
    """Authenticate the current request context as ``user`` (the user_loader
    runs on first current_user access and resolves this id)."""
    session["_user_id"] = f"local:{user.id}"
    session["_fresh"] = True


def test_unauthenticated_connect_is_refused(app):
    # No logged-in user -> current_user is anonymous -> handler must refuse.
    with app.test_request_context():
        with pytest.raises(ConnectionRefusedError):
            events.handle_connect()


def test_authenticated_connect_emits_status(app, make_local_user, monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "emit", lambda event, *a, **k: emitted.append(event))
    user = make_local_user()
    with app.test_request_context():
        _login(user)
        events.handle_connect()
    assert "status" in emitted


def test_authenticated_join_log_room_joins_and_echoes(app, db, make_local_user, make_project, make_server,
                                                      make_container, monkeypatch):
    emitted = []
    joined = []
    monkeypatch.setattr(events, "join_room", lambda room: joined.append(room))
    monkeypatch.setattr(
        events, "emit", lambda event, *a, **k: emitted.append((event, k.get("room")))
    )
    user = make_local_user()
    project = make_project(owner=user)
    server = make_server()
    container = make_container(owner=user, project=project, server=server)
    with app.test_request_context():
        _login(user)
        events.handle_join_log_room({"container_id": container.id})
    assert joined == [str(container.id)]  # room is named after the container id
    assert ("status", str(container.id)) in emitted  # and a status is echoed into it


def test_join_log_room_denied_for_non_owner(app, db, make_local_user, make_project, make_server, make_container,
                                            monkeypatch):
    """A non-owner, non-admin user must not join another user's log room, since
    replayed logs contain the generated container password and SSH material."""
    joined = []
    replayed = []
    monkeypatch.setattr(events, "join_room", lambda room: joined.append(room))
    monkeypatch.setattr(events, "emit", lambda event, *a, **k: None)
    monkeypatch.setattr(events, "_replay_saved_logs", lambda cid: replayed.append(cid))

    owner = make_local_user(username="sock_owner")
    intruder = make_local_user(username="sock_intruder")
    project = make_project(owner=owner)
    server = make_server()
    container = make_container(owner=owner, project=project, server=server)

    with app.test_request_context():
        _login(intruder)
        events.handle_join_log_room({"container_id": container.id})

    assert joined == []  # never joined the room
    assert replayed == []  # and no history replayed to the intruder


def test_join_log_room_allowed_for_owner_and_admin(app, db, make_local_user, make_project, make_server, make_container,
                                                   monkeypatch):
    owner = make_local_user(username="sock_owner2")
    admin = make_local_user(username="sock_admin", is_admin=True)
    project = make_project(owner=owner)
    server = make_server()
    container = make_container(owner=owner, project=project, server=server)

    for user in (owner, admin):
        joined = []
        monkeypatch.setattr(events, "join_room", lambda room, _j=joined: _j.append(room))
        monkeypatch.setattr(events, "emit", lambda event, *a, **k: None)
        monkeypatch.setattr(events, "_replay_saved_logs", lambda cid: None)
        with app.test_request_context():
            _login(user)
            events.handle_join_log_room({"container_id": container.id})
        assert joined == [str(container.id)], f"{user.username} should be allowed"


def test_replay_log_lines_strips_ansi_and_blanks():
    text = "line one\n\x1b[31mred\x1b[0m\n\n  keep leading  \n"
    assert events._log_lines_for_replay(text) == ["line one", "red", "  keep leading"]


def test_replay_log_lines_handles_empty_and_none():
    assert events._log_lines_for_replay("") == []
    assert events._log_lines_for_replay(None) == []
