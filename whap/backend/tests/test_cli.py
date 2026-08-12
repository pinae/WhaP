"""Tests for the ``create-admin`` CLI command.

Uses the shared ``app``/``runner`` fixtures from conftest (which seed the
Admins group with id 0); the local app/runner fixtures this file used to carry
were removed during consolidation.
"""
from app import db
from app.models import LocalUser, GroupMembership


def test_create_admin_command(runner, app):
    """The create-admin command creates the user and adds it to the Admins group."""
    username = "testadmin"
    password = "securepassword"
    inputs = [username, password, password]  # username, password, confirmation

    result = runner.invoke(args=["create-admin"], input="\n".join(inputs))

    assert result.exit_code == 0
    assert f"Admin user '{username}' created and added to Admins group." in result.output

    user = LocalUser.query.filter_by(username=username).first()
    assert user is not None
    assert user.check_password(password)

    membership = GroupMembership.query.filter_by(
        user_uid=f"local:{user.id}", group_id=0
    ).first()
    assert membership is not None
    assert membership.is_group_admin is True


def test_create_admin_duplicate_user(runner, app):
    """create-admin refuses to clobber an existing username."""
    existing_user = LocalUser(username="existing")
    existing_user.set_password("password123")
    db.session.add(existing_user)
    db.session.commit()

    result = runner.invoke(args=["create-admin"], input="\n".join(["existing", "pw", "pw"]))

    assert result.exit_code == 0
    assert "Error: Username 'existing' already exists." in result.output
