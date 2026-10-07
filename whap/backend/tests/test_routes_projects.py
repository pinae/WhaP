"""Tests for the project routes (app/routes/projects.py)."""
import pytest


def test_update_project_does_not_print_to_stdout(client, db, capsys, make_local_user, make_project, login_as):
    """update_project used to `print(data)`, dumping request bodies to stdout."""
    owner = make_local_user(username="proj_owner")
    project = make_project(owner=owner, name="orig")
    login_as(owner)

    resp = client.put(f"/api/projects/{project.id}", json={"description": "updated"})
    assert resp.status_code in (200, 204), resp.get_data(as_text=True)

    out = capsys.readouterr().out
    assert "updated" not in out


# --- Ownership boundaries (WP5) --------------------------------------------
# Projects are owner-only: update/delete require ownership. Note this is
# intentionally stricter than containers -- admins are NOT granted a bypass here.

def test_update_project_denied_for_non_owner(client, db, make_local_user, make_project, login_as):
    owner = make_local_user(username="proj_owner_u")
    other = make_local_user(username="proj_other_u")
    project = make_project(owner=owner, name="owned")
    login_as(other)
    resp = client.put(f"/api/projects/{project.id}", json={"description": "x"})
    assert resp.status_code == 403, resp.get_data(as_text=True)


def test_delete_project_denied_for_non_owner(client, db, make_local_user, make_project, login_as):
    owner = make_local_user(username="proj_owner_d")
    other = make_local_user(username="proj_other_d")
    project = make_project(owner=owner, name="owned2")
    login_as(other)
    resp = client.delete(f"/api/projects/{project.id}")
    assert resp.status_code == 403, resp.get_data(as_text=True)


def test_owner_reads_project_details_with_shares(client, db, make_local_user, make_project, login_as):
    from app.models import ProjectShare
    owner = make_local_user(username="proj_owner_r")
    project = make_project(owner=owner, name="readable")
    db.session.add(ProjectShare(project_id=project.id, user_uid="ldap:friend", is_writable=True))
    db.session.commit()
    login_as(owner)

    resp = client.get(f"/api/projects/{project.id}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["shares"] == [
        {"id": 1, "project_id": project.id, "user_uid": "ldap:friend", "is_writable": True}]


@pytest.mark.parametrize("who", ["stranger", "share_recipient", "admin"])
def test_project_details_hidden_from_everyone_but_the_owner(client, db, make_local_user, make_project,
                                                           login_as, who):
    """Used to return any project, with its share list, to any logged-in user.
    A share recipient may mount the project but shouldn't see who else may;
    admins have /admin/projects. 404, not 403, so ids can't be probed."""
    from app.models import ProjectShare
    owner = make_local_user(username="proj_owner_h")
    project = make_project(owner=owner, name="private")
    viewer = make_local_user(username=f"viewer_{who}", is_admin=(who == "admin"))
    if who == "share_recipient":
        db.session.add(ProjectShare(project_id=project.id, user_uid=f"local:{viewer.id}"))
        db.session.commit()
    login_as(viewer)

    resp = client.get(f"/api/projects/{project.id}")
    assert resp.status_code == 404, resp.get_data(as_text=True)
    assert "shares" not in resp.get_data(as_text=True)


def test_project_details_for_missing_and_hidden_ids_look_the_same(client, db, make_local_user, make_project,
                                                                  login_as):
    owner = make_local_user(username="proj_owner_p")
    hidden = make_project(owner=owner, name="hidden")
    login_as(make_local_user(username="prober"))
    assert client.get(f"/api/projects/{hidden.id}").status_code == client.get("/api/projects/9999").status_code


def test_delete_project_allowed_for_owner(client, db, make_local_user, make_project, login_as, monkeypatch):
    import app.routes.projects as projects
    # Neutralise the filesystem-delete job enqueue so the test stays in-process.
    monkeypatch.setattr(projects, "enqueue_delete_directory", lambda *a, **k: None)
    owner = make_local_user(username="proj_owner_ok")
    project = make_project(owner=owner, name="owned3")
    login_as(owner)
    resp = client.delete(f"/api/projects/{project.id}")
    assert resp.status_code == 204, resp.get_data(as_text=True)


# --- WP6: owner-scoped project-name uniqueness ------------------------------
# Name uniqueness must be per-owner, not global: two different users may each
# have a project called "thesis", but one user cannot have two of the same name.

def test_two_users_may_reuse_project_name(db, make_local_user, client_for, monkeypatch):
    import app.routes.projects as projects
    monkeypatch.setattr(projects, "enqueue_create_directory", lambda *a, **k: None)

    a = make_local_user(username="userA")
    b = make_local_user(username="userB")

    r1 = client_for(a).post("/api/projects", json={"name": "thesis"})
    assert r1.status_code == 201, r1.get_data(as_text=True)

    r2 = client_for(b).post("/api/projects", json={"name": "thesis"})
    assert r2.status_code == 201, r2.get_data(as_text=True)


def test_same_user_cannot_duplicate_name(client, db, make_local_user, login_as, monkeypatch):
    import app.routes.projects as projects
    monkeypatch.setattr(projects, "enqueue_create_directory", lambda *a, **k: None)

    a = make_local_user(username="userDup")
    login_as(a)
    assert client.post("/api/projects", json={"name": "thesis"}).status_code == 201
    dup = client.post("/api/projects", json={"name": "thesis"})
    assert dup.status_code == 409, dup.get_data(as_text=True)
    # The conflict message must not leak another user's project ownership;
    # here it's the same user, so 409 is expected and correct.


def test_admin_update_project_reassigns_owner_without_rename(admin_client, db, make_local_user, make_project,
                                                             monkeypatch):
    """Owner reassignment must not be gated behind providing a new name."""
    import app.routes.projects as projects
    monkeypatch.setattr(projects, "enqueue_rename_directory", lambda *a, **k: None)

    owner = make_local_user(username="orig_owner")
    new_owner = make_local_user(username="new_owner")
    project = make_project(owner=owner, name="proj_reassign")

    resp = admin_client.put(f"/api/admin/projects/{project.id}", json={
        "owner_local_user_id": new_owner.id,
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)

    db.session.refresh(project)
    assert project.owner_local_user_id == new_owner.id
    assert project.name == "proj_reassign"  # unchanged


def test_same_owner_duplicate_blocked_at_db_level(app, db, make_local_user):
    """Defense in depth: the partial unique index rejects a same-owner duplicate
    even if a code path skips the route-level check."""
    import sqlalchemy.exc
    from app.models import Project
    owner = make_local_user(username="db_dup_owner")
    db.session.add(Project(name="dup", owner_local_user_id=owner.id))
    db.session.commit()
    db.session.add(Project(name="dup", owner_local_user_id=owner.id))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


# --- Read-write shares need a group-writable directory ----------------------

def _queued_modes(db):
    import json
    from app.models import FileOperationJob
    jobs = db.session.scalars(db.select(FileOperationJob).filter_by(operation="create_directory")).all()
    return [json.loads(job.payload)["mode"] for job in jobs]


def test_a_new_project_directory_is_created_group_writable(client, db, make_local_user, login_as):
    from app.services.local_file_service import PROJECT_DIR_MODE
    login_as(make_local_user(username="rw_owner"))
    assert client.post("/api/projects", json={"name": "shared"}).status_code == 201
    assert _queued_modes(db) == [PROJECT_DIR_MODE]


@pytest.mark.parametrize("writable, queued", [(True, 1), (False, 0)])
def test_a_writable_share_reapplies_the_mode(client, db, make_local_user, make_project, login_as, writable, queued):
    """Directories made before the mode existed are 0755; sharing one
    read-write must fix that, or nobody but the owner can write to it."""
    owner = make_local_user(username="rw_owner2")
    project = make_project(owner=owner, name="older")
    login_as(owner)
    resp = client.put(f"/api/projects/{project.id}",
                      json={"shares": [{"user_uid": "ldap:someone", "is_writable": writable}]})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(_queued_modes(db)) == queued


# --- Admin-made projects belong to their owner, on disk too -----------------

def _queued_owner(db, operation):
    import json
    from app.models import FileOperationJob
    job = db.session.scalar(db.select(FileOperationJob).filter_by(operation=operation))
    return json.loads(job.payload)["user_identifier"]


@pytest.mark.parametrize("owner", ["ldap", "local"])
def test_an_admin_created_project_directory_belongs_to_its_owner(admin_client, db, make_local_user, owner):
    """The directory was queued as the admin, so it ended up owned by the admin."""
    if owner == "ldap":
        body, expected = {"owner_uid": "e2e-alice"}, "ldap:e2e-alice"
    else:
        user = make_local_user(username="owned_by_admin")
        body, expected = {"owner_local_user_id": user.id}, f"local:{user.id}"
    resp = admin_client.post("/api/admin/projects", json={"name": "given", **body})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert _queued_owner(db, "create_directory") == expected


def test_reassigning_a_project_moves_its_directory_to_the_new_owner(admin_client, db, make_local_user,
                                                                    make_project):
    project = make_project(owner=make_local_user(username="first_owner"), name="handed_on")
    resp = admin_client.put(f"/api/admin/projects/{project.id}", json={"owner_uid": "e2e-bob"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _queued_owner(db, "rename_directory") == "ldap:e2e-bob"
