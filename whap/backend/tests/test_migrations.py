"""The migrations, run as production runs them: on Postgres, from an empty database.

The rest of the suite builds its schema with ``db.create_all()``, so it never
sees what the migrations actually produce; a unique index the models had
dropped once survived in every migrated database. These tests compare the
migrated schema with the models and check the data migrations.

The early migrations drop constraints by the names Postgres gives them, so the
chain does not run on SQLite. Point WHAP_TEST_MIGRATION_DATABASE_URL at a
scratch Postgres database to run them; everything in its public schema is
dropped.
"""
import json
import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade

from app import create_app, db as _db
from conftest import _build_config

URL = os.environ.get("WHAP_TEST_MIGRATION_DATABASE_URL")
MIGRATIONS = os.path.join(os.path.dirname(__file__), "..", "migrations")

pytestmark = pytest.mark.skipif(not URL, reason="WHAP_TEST_MIGRATION_DATABASE_URL is not set")

BEFORE_NOTIFICATIONS = "0736a97914ad"


@pytest.fixture
def empty_db(tmp_path):
    config = _build_config(tmp_path)
    config.SQLALCHEMY_DATABASE_URI = URL
    application = create_app(config)
    with application.app_context():
        _db.session.execute(_db.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        _db.session.commit()
        yield application
        _db.session.remove()
        _db.engine.dispose()


def sql(statement, **params):
    result = _db.session.execute(_db.text(statement), params)
    _db.session.commit()
    return result


def test_migrated_schema_matches_the_models(empty_db):
    upgrade(directory=MIGRATIONS)
    with _db.engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), _db.metadata) == []


def test_two_owners_may_each_have_a_project_of_the_same_name(empty_db):
    upgrade(directory=MIGRATIONS)
    sql("INSERT INTO project (name, owner_uid) VALUES ('thesis', 'alice'), ('thesis', 'bob')")
    assert sql("SELECT count(*) FROM project WHERE name = 'thesis'").scalar() == 2


def _container(server_id, project_id, *jobs):
    container_id = sql(
        "INSERT INTO container_instance (user_uid, project_id, compute_server_id, image_name, gpus, status) "
        "VALUES ('alice', :p, :s, 'worker_local_ubuntu2404_ssh', '0', 'RUNNING') RETURNING id",
        p=project_id, s=server_id).scalar()
    for action, extravars in jobs:
        sql("INSERT INTO ansible_job (container_instance_id, server_id, status, action, log, playbook, extravars) "
            "VALUES (:c, :s, 'SUCCESSFUL', :a, '', '', :e)",
            c=container_id, s=server_id, a=action, e=extravars)
    return container_id


def test_existing_mounts_are_copied_from_the_create_jobs(empty_db):
    datasets = empty_db.config["DATASETS_BASE_PATH"]
    upgrade(directory=MIGRATIONS, revision=BEFORE_NOTIFICATIONS)
    server = sql("INSERT INTO compute_server (hostname, ssh_port, gpu_count) VALUES ('tycho', 22, 1) "
                 "RETURNING id").scalar()
    project = sql("INSERT INTO project (name, owner_uid) VALUES ('thesis', 'alice') RETURNING id").scalar()
    volumes = [
        {"host_path": f"{datasets}/coco", "container_path": "/home/alice/coco", "is_writable": False},
        {"host_path": "/data/bob/shared", "container_path": "/home/alice/shared", "is_writable": True},
    ]
    with_mounts = _container(
        server, project,
        ("create", json.dumps({"additional_volumes": volumes, "ttl_date": "2026-11-01"})),
        # A later create job (a retry) must not add the mounts twice.
        ("create", json.dumps({"additional_volumes": volumes})),
        ("stop", json.dumps({"additional_volumes": volumes})),
    )
    _container(server, project, ("create", "not json"))
    _container(server, project, ("create", json.dumps({"additional_volumes": [{"host_path": "/x"}]})))
    _container(server, project, ("create", None))

    upgrade(directory=MIGRATIONS)

    rows = sql("SELECT container_id, host_path, container_path, writable, dataset "
               "FROM container_mount ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        (with_mounts, f"{datasets}/coco", "/home/alice/coco", False, "coco"),
        (with_mounts, "/data/bob/shared", "/home/alice/shared", True, None),
    ]


def test_the_notification_migration_can_be_undone(empty_db):
    upgrade(directory=MIGRATIONS)
    downgrade(directory=MIGRATIONS, revision=BEFORE_NOTIFICATIONS)
    tables = {r[0] for r in sql("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert not tables & {"notification", "notification_delivery", "notification_settings", "container_mount"}
    upgrade(directory=MIGRATIONS)
