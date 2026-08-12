"""Unit tests for the shared container-access predicate used by both the REST
route guard (check_container_permission) and the Socket.IO log-room join."""
from app.services.permissions_service import user_can_access_container


def test_owner_can_access(app, db, make_local_user, make_project, make_server, make_container):
    owner = make_local_user(username="pred_owner")
    container = make_container(
        owner=owner, project=make_project(owner=owner), server=make_server()
    )
    from app.user_management import LocalUserWrapper
    with app.test_request_context():
        assert user_can_access_container(LocalUserWrapper(owner), container) is True


def test_non_owner_cannot_access(app, db, make_local_user, make_project, make_server, make_container):
    owner = make_local_user(username="pred_owner2")
    other = make_local_user(username="pred_other")
    container = make_container(
        owner=owner, project=make_project(owner=owner), server=make_server()
    )
    from app.user_management import LocalUserWrapper
    with app.test_request_context():
        assert user_can_access_container(LocalUserWrapper(other), container) is False


def test_admin_can_access(app, db, make_local_user, make_project, make_server, make_container):
    owner = make_local_user(username="pred_owner3")
    admin = make_local_user(username="pred_admin", is_admin=True)
    container = make_container(
        owner=owner, project=make_project(owner=owner), server=make_server()
    )
    from app.user_management import LocalUserWrapper
    with app.test_request_context():
        assert user_can_access_container(LocalUserWrapper(admin), container) is True


def test_none_container_is_false(app, db, make_local_user):
    user = make_local_user(username="pred_u")
    from app.user_management import LocalUserWrapper
    with app.test_request_context():
        assert user_can_access_container(LocalUserWrapper(user), None) is False
