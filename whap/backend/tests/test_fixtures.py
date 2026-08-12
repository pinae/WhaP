"""WP0 sanity checks for the shared route-test factories.

These pin down that the new factories in ``conftest.py`` create persisted,
correctly-owned objects, so the ownership/volume packages can rely on them
without re-checking the plumbing in every test.
"""
from app.models import Project, ContainerInstance, UserSSHKey, StaticAddress, Network


def test_make_project_is_owned_by_user(db, make_local_user, make_project):
    user = make_local_user()
    project = make_project(owner=user, name="thesis")

    persisted = db.session.get(Project, project.id)
    assert persisted is not None
    assert persisted.name == "thesis"
    assert persisted.owner_local_user_id == user.id
    assert persisted.owner_uid is None
    assert persisted.owner_group_id is None


def test_make_ssh_key_is_owned_by_user(db, make_local_user, make_ssh_key):
    user = make_local_user()
    key = make_ssh_key(owner=user, name="laptop")

    persisted = db.session.get(UserSSHKey, key.id)
    assert persisted is not None
    assert persisted.user_uid == f"local:{user.id}"
    assert persisted.name == "laptop"


def test_make_container_is_owned_and_persisted(db, make_local_user, make_project, make_server, make_container):
    user = make_local_user()
    project = make_project(owner=user)
    server = make_server()
    container = make_container(owner=user, project=project, server=server)

    persisted = db.session.get(ContainerInstance, container.id)
    assert persisted is not None
    assert persisted.user_local_user_id == user.id
    assert persisted.user_uid is None
    assert persisted.project_id == project.id
    assert persisted.compute_server_id == server.id


def test_make_static_address_links_network_and_servers(db, make_server, make_network, make_static_address):
    server = make_server()
    network = make_network(name="lab-private")
    address = make_static_address(network=network, servers=[server])

    persisted = db.session.get(StaticAddress, address.id)
    assert persisted is not None
    assert persisted.network_id == network.id
    assert server in persisted.available_servers
    net = db.session.get(Network, network.id)
    assert net.name == "lab-private"
