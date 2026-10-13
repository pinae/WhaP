"""The container lists stay fast as containers add up.

The admin's list took 3-5 s on production with ~50 containers: every row looked
its owner up in LDAP (a new TLS connection, bind and search, to return the uid
the row already had), ran its own queries for the latest job, project, server
and address, and carried that job's whole Ansible log, which the table never
shows. These tests pin the number of queries and LDAP lookups, independent of
how many containers there are.
"""
import pytest
from sqlalchemy import event

from app.models import AnsibleJob, ContainerInstance, Project, StaticAddress

LOG = "TASK [docker_container] ok\n" * 2000  # an Ansible log of ~54 kB


@pytest.fixture
def many_containers(db, make_server, make_network, make_local_user):
    """50 containers, 45 of LDAP users and 5 of a local user, each with two jobs and an address."""
    server = make_server(hostname="tycho")
    network = make_network(name="lab")
    local = make_local_user(username="carol")
    for i in range(50):
        owner = {"user_local_user_id": local.id} if i % 10 == 0 else {"user_uid": f"user{i}"}
        project = Project(name=f"p{i}", **({"owner_local_user_id": local.id} if "user_local_user_id" in owner
                                           else {"owner_uid": owner["user_uid"]}))
        address = StaticAddress(ip_address=f"10.0.{i // 200}.{i % 200 + 10}", mac_address=f"02:00:00:00:00:{i:02x}",
                                network_id=network.id)
        db.session.add_all([project, address])
        db.session.flush()
        container = ContainerInstance(project_id=project.id, compute_server_id=server.id, gpus="0",
                                      image_name="worker_local_ubuntu2404_ssh", status="RUNNING",
                                      static_address_id=address.id, **owner)
        db.session.add(container)
        db.session.flush()
        db.session.add_all([AnsibleJob(container_instance_id=container.id, server_id=server.id, action="create",
                                       status="SUCCESSFUL", log=LOG),
                            AnsibleJob(container_instance_id=container.id, server_id=server.id, action="stop",
                                       status="SUCCESSFUL", log="stopped " + str(i))])
    db.session.commit()
    db.session.expire_all()


@pytest.fixture
def ldap_lookups(monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.ldap_service.get_ldap_user_details",
                        lambda uid: calls.append(uid) or {"uid": uid, "uidNumber": "1", "gidNumber": "1"})
    return calls


@pytest.fixture
def queries(db):
    statements = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", count)
    yield statements
    event.remove(db.engine, "before_cursor_execute", count)


def test_the_admin_list_asks_ldap_nothing_and_needs_few_queries(admin_client, many_containers, ldap_lookups,
                                                                queries):
    queries.clear()
    response = admin_client.get("/api/admin/containers")
    assert response.status_code == 200
    rows = response.get_json()
    assert len(rows) == 50
    assert ldap_lookups == []
    assert len(queries) <= 10, f"{len(queries)} queries"
    assert len(response.data) < 50_000, f"{len(response.data)} bytes: no Ansible logs in the list"
    assert {r["username"] for r in rows} >= {"carol", "user1"}
    assert all("ansible_log" not in r for r in rows)
    assert rows[1]["ip_address"].startswith("10.0.0.") and rows[1]["server"] == "tycho"


def test_a_users_list_shows_each_containers_latest_log_without_a_query_per_container(
        client, db, many_containers, ldap_lookups, queries, login_as):
    from app.models import LocalUser
    login_as(db.session.scalar(db.select(LocalUser).filter_by(username="carol")))
    queries.clear()
    rows = client.get("/api/containers").get_json()
    assert len(rows) == 5
    assert all(r["ansible_log"].startswith("stopped ") for r in rows), "the latest job's log"
    assert ldap_lookups == []
    assert len(queries) <= 10, f"{len(queries)} queries"
