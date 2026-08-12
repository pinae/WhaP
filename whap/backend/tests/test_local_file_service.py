"""Tests for app.services.local_file_service.

These do real filesystem work under tmp_path but must not require root, so
``os.chown`` is patched to a no-op by default (and made to raise in the tests
that exercise the ownership-error branches). ``_get_user_ids`` is driven with a
real LocalUserWrapper (config defaults, no root) and a mocked LDAP lookup.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import local_file_service as lfs
from app.user_management import LocalUserWrapper, LdapUserWrapper


@pytest.fixture
def local_user(app, db, make_local_user):
    return LocalUserWrapper(make_local_user(username="fileuser"))


@pytest.fixture(autouse=True)
def _noop_chown():
    """Ownership changes need root; make chown a no-op so the real fs logic runs."""
    with patch("app.services.local_file_service.os.chown", lambda *a, **k: None):
        yield


# --- _get_user_ids ----------------------------------------------------------

def test_get_user_ids_local_uses_config_defaults(app, local_user):
    app.config["DEFAULT_CONTAINER_UID"] = 1500
    app.config["DEFAULT_CONTAINER_GID"] = 1600
    assert lfs._get_user_ids(local_user) == (1500, 1600)


def test_get_user_ids_ldap_fetches_fresh(app, monkeypatch):
    monkeypatch.setattr(
        lfs.ldap_service, "get_ldap_user_details",
        lambda uid: {"uid": uid, "uidNumber": "4242", "gidNumber": "4343"},
    )
    w = LdapUserWrapper({"uid": "jdoe"})
    assert lfs._get_user_ids(w) == (4242, 4343)


def test_get_user_ids_ldap_missing_returns_none(app, monkeypatch):
    monkeypatch.setattr(lfs.ldap_service, "get_ldap_user_details", lambda uid: None)
    w = LdapUserWrapper({"uid": "ghost"})
    assert lfs._get_user_ids(w) == (None, None)


def test_get_user_ids_unknown_type_returns_none(app):
    assert lfs._get_user_ids(object()) == (None, None)


# --- create_directory -------------------------------------------------------

def test_create_directory_new(app, local_user, tmp_path):
    target = tmp_path / "proj"
    lfs.create_directory(target, local_user)
    assert target.is_dir()


def test_create_directory_idempotent_existing(app, local_user, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    lfs.create_directory(target, local_user)  # must not raise
    assert target.is_dir()


def test_create_directory_aborts_on_missing_ids(app, tmp_path, monkeypatch):
    monkeypatch.setattr(lfs, "_get_user_ids", lambda user: (None, None))
    target = tmp_path / "shouldnotexist"
    lfs.create_directory(target, object())
    assert not target.exists()


def test_create_directory_chown_error_is_logged_not_raised(app, local_user, tmp_path):
    target = tmp_path / "proj"
    with patch("app.services.local_file_service.os.chown", side_effect=OSError("nope")):
        lfs.create_directory(target, local_user)  # must swallow the OSError
    assert target.is_dir()


# --- rename_directory -------------------------------------------------------

def test_rename_directory_moves(app, local_user, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "marker.txt").write_text("x")
    new = tmp_path / "new"
    lfs.rename_directory(old, new, local_user)
    assert not old.exists()
    assert (new / "marker.txt").read_text() == "x"


def test_rename_directory_target_exists_is_noop(app, local_user, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    lfs.rename_directory(old, new, local_user)
    # Source left untouched because target already exists.
    assert old.is_dir()


def test_rename_directory_missing_source_is_noop(app, local_user, tmp_path):
    old = tmp_path / "gone"
    new = tmp_path / "new"
    lfs.rename_directory(old, new, local_user)
    assert not new.exists()


def test_rename_directory_aborts_on_missing_ids(app, tmp_path, monkeypatch):
    monkeypatch.setattr(lfs, "_get_user_ids", lambda user: (None, None))
    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    lfs.rename_directory(old, new, object())
    assert old.is_dir() and not new.exists()


# --- delete_directory -------------------------------------------------------

def test_delete_directory_removes(app, tmp_path):
    target = tmp_path / "tokill"
    target.mkdir()
    (target / "f.txt").write_text("data")
    lfs.delete_directory(target)
    assert not target.exists()


def test_delete_directory_missing_is_noop(app, tmp_path):
    lfs.delete_directory(tmp_path / "never")  # must not raise


def test_delete_directory_refuses_non_directory(app, tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    lfs.delete_directory(f)
    assert f.exists()  # a file is not a directory -> left alone


# --- ensure_lines_in_file ---------------------------------------------------

def test_ensure_lines_creates_file_with_lines(app, local_user, tmp_path):
    f = tmp_path / "sub" / "authorized_keys"
    lfs.ensure_lines_in_file(f, ["ssh-rsa AAA", "ssh-rsa BBB"], local_user)
    content = f.read_text().splitlines()
    assert content == ["ssh-rsa AAA", "ssh-rsa BBB"]


def test_ensure_lines_appends_only_missing(app, local_user, tmp_path):
    f = tmp_path / "keys"
    f.parent.mkdir(exist_ok=True)
    f.write_text("ssh-rsa AAA\n")
    lfs.ensure_lines_in_file(f, ["ssh-rsa AAA", "ssh-rsa CCC"], local_user)
    lines = f.read_text().splitlines()
    assert lines.count("ssh-rsa AAA") == 1  # not duplicated
    assert "ssh-rsa CCC" in lines


def test_ensure_lines_all_present_is_noop(app, local_user, tmp_path):
    f = tmp_path / "keys"
    f.parent.mkdir(exist_ok=True)
    f.write_text("line1\nline2\n")
    lfs.ensure_lines_in_file(f, ["line1", "line2"], local_user)
    assert f.read_text() == "line1\nline2\n"  # unchanged


def test_ensure_lines_aborts_on_missing_ids(app, tmp_path, monkeypatch):
    monkeypatch.setattr(lfs, "_get_user_ids", lambda user: (None, None))
    f = tmp_path / "keys"
    lfs.ensure_lines_in_file(f, ["x"], object())
    assert not f.exists()


# --- get_gids_for_paths -----------------------------------------------------

def test_get_gids_for_paths_dedupes_existing(app, tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    gids = lfs.get_gids_for_paths([str(d1), d2, tmp_path / "missing"])
    # Both dirs share this process's gid -> one unique entry; missing dir skipped.
    assert isinstance(gids, list)
    assert gids == [d1.stat().st_gid]


def test_get_gids_for_paths_skips_non_directories(app, tmp_path):
    f = tmp_path / "notadir"
    f.write_text("x")
    assert lfs.get_gids_for_paths([f]) == []


# --- Ownership-correction and error branches --------------------------------

def test_create_directory_corrects_ownership_on_existing(app, local_user, tmp_path):
    """Existing dir whose owner differs from the target uid/gid triggers chown."""
    target = tmp_path / "proj"
    target.mkdir()
    # Force a uid/gid that won't match the dir's real owner so the branch fires.
    with patch.object(lfs, "_get_user_ids", return_value=(999999, 888888)):
        chown_calls = []
        with patch("app.services.local_file_service.os.chown",
                   side_effect=lambda *a, **k: chown_calls.append(a)):
            lfs.create_directory(target, local_user)
    assert chown_calls, "chown should be called to correct ownership"


def test_create_directory_corrects_ownership_chown_error(app, local_user, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    with patch.object(lfs, "_get_user_ids", return_value=(999999, 888888)):
        with patch("app.services.local_file_service.os.chown", side_effect=OSError("denied")):
            lfs.create_directory(target, local_user)  # OSError swallowed
    assert target.is_dir()


def test_rename_target_exists_corrects_ownership(app, local_user, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    new.mkdir()
    with patch.object(lfs, "_get_user_ids", return_value=(999999, 888888)):
        chown_calls = []
        with patch("app.services.local_file_service.os.chown",
                   side_effect=lambda *a, **k: chown_calls.append(a)):
            lfs.rename_directory(old, new, local_user)
    assert chown_calls


def test_rename_os_error_is_logged(app, local_user, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    new = tmp_path / "new"
    with patch("app.services.local_file_service.os.rename", side_effect=OSError("boom")):
        lfs.rename_directory(old, new, local_user)  # must swallow
    assert old.is_dir()  # rename failed, source remains


def test_delete_directory_rmtree_error_is_logged(app, tmp_path):
    target = tmp_path / "tokill"
    target.mkdir()
    with patch("app.services.local_file_service.shutil.rmtree", side_effect=OSError("busy")):
        lfs.delete_directory(target)  # must swallow
    assert target.is_dir()


def test_ensure_lines_read_error_aborts(app, local_user, tmp_path):
    f = tmp_path / "keys"
    f.parent.mkdir(exist_ok=True)
    f.write_text("existing\n")
    # Fail the read of the existing file -> abort before writing.
    with patch("builtins.open", side_effect=IOError("cannot read")):
        lfs.ensure_lines_in_file(f, ["new"], local_user)
    assert f.read_text() == "existing\n"  # untouched


def test_ensure_lines_all_present_corrects_ownership(app, local_user, tmp_path):
    f = tmp_path / "keys"
    f.parent.mkdir(exist_ok=True)
    f.write_text("line1\n")
    with patch.object(lfs, "_get_user_ids", return_value=(999999, 888888)):
        chown_calls = []
        with patch("app.services.local_file_service.os.chown",
                   side_effect=lambda *a, **k: chown_calls.append(a)):
            lfs.ensure_lines_in_file(f, ["line1"], local_user)  # nothing to add
    assert chown_calls  # ownership corrected on the existing file


def test_ensure_lines_write_error_is_logged(app, local_user, tmp_path):
    f = tmp_path / "sub" / "keys"
    real_open = open

    def flaky_open(path, mode="r", *a, **k):
        if "a" in mode:  # fail only the append
            raise IOError("disk full")
        return real_open(path, mode, *a, **k)

    with patch("builtins.open", side_effect=flaky_open):
        lfs.ensure_lines_in_file(f, ["x"], local_user)  # must swallow


def test_get_gids_stat_error_is_logged(app, tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    # is_dir() must still pass; only the .stat() inside the try should raise.
    with patch("pathlib.Path.is_dir", return_value=True), \
            patch("pathlib.Path.stat", side_effect=OSError("stat failed")):
        gids = lfs.get_gids_for_paths([d])
    assert gids == []


def test_rename_target_exists_chown_error_is_logged(app, local_user, tmp_path):
    old = tmp_path / "old";
    old.mkdir()
    new = tmp_path / "new";
    new.mkdir()
    with patch.object(lfs, "_get_user_ids", return_value=(999999, 888888)):
        with patch("app.services.local_file_service.os.chown", side_effect=OSError("denied")):
            lfs.rename_directory(old, new, local_user)  # correction chown fails -> swallowed
    assert old.is_dir()


def test_ensure_lines_existing_ownership_chown_error_is_logged(app, local_user, tmp_path):
    f = tmp_path / "keys";
    f.parent.mkdir(exist_ok=True);
    f.write_text("line1\n")
    with patch.object(lfs, "_get_user_ids", return_value=(999999, 888888)):
        with patch("app.services.local_file_service.os.chown", side_effect=OSError("denied")):
            lfs.ensure_lines_in_file(f, ["line1"], local_user)  # nothing to add, chown fails
    assert f.read_text() == "line1\n"
