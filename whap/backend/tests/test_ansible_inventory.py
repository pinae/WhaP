"""Regression tests for the per-job Ansible inventory.

Two properties must both hold:
  * the host file is written into the SHARED inventory dir, so ansible still
    resolves group_vars/host_vars there (the SSH connection user/key) -- writing
    it into a bare per-job dir made ansible connect as root;
  * the filename is per-job, so two jobs running at once never overwrite each
    other's target host (the original bug was a single 99_dynamic_hosts.ini).
"""
import os
import types

from app.services.ansible_service import write_job_inventory


def _server(hostname="tycho", ssh_port=22):
    return types.SimpleNamespace(hostname=hostname, ssh_port=ssh_port)


def test_written_into_shared_dir_with_per_job_filename(tmp_path):
    inv_dir = tmp_path / "inventory"
    inv_dir.mkdir()

    path = write_job_inventory(str(inv_dir), 46, _server("tycho", 2222))

    # Stays in the shared inventory dir (where group_vars/host_vars live)...
    assert os.path.dirname(path) == str(inv_dir)
    # ...but under a per-job filename.
    assert os.path.basename(path) == "99_dynamic_hosts_job_46.ini"
    content = open(path).read()
    assert "[job_targets]" in content
    assert "tycho ansible_port=2222" in content


def test_concurrent_jobs_use_distinct_files_and_dont_clobber(tmp_path):
    inv_dir = tmp_path / "inventory"
    inv_dir.mkdir()
    # A sibling file (stands in for group_vars/host_vars) must survive untouched.
    (inv_dir / "group_vars").mkdir()
    (inv_dir / "group_vars" / "all.yml").write_text("ansible_user: deploy\n")

    p45 = write_job_inventory(str(inv_dir), 45, _server("host-a", 22))
    p46 = write_job_inventory(str(inv_dir), 46, _server("host-b", 22))

    assert p45 != p46  # distinct filenames
    assert "host-a" in open(p45).read()  # job 46 didn't clobber job 45
    assert "host-b" in open(p46).read()
    # The shared group_vars are left intact.
    assert (inv_dir / "group_vars" / "all.yml").read_text() == "ansible_user: deploy\n"
