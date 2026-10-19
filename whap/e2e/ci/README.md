# Running the end-to-end tests from Semaphore

`e2e.yml` runs the suite as one Ansible play. Semaphore connects to victor over
SSH, as the user who runs the tests by hand, and there:

1. checks out the branch to test in `~/WhaP` (`e2e_branch`, `main` unless you
   choose another) and fast-forwards it to GitHub's,
2. checks that the rig's WhaP (`/docker/whap/WhaP`) runs that same commit, and
   stops if not: deploy the branch first,
3. builds the container images on tycho and pushes them to the registry
   (`docker exec whap-worker flask build-images --server tycho`),
4. runs `whap/e2e/nightly/run.sh`: results in `~/whap-e2e-results/<date>/`
   on victor, `latest` pointing at the newest,
5. prints the summary and the failed tests, and fails if the suite failed.

victor needs nothing new: the run uses the same checkout, `rig.toml`, uv and
docker group as a manual run.

## Setup

The names in *italics* are suggestions. Menus are those of Semaphore UI 2.x;
older versions call Variable Groups "Environment".

### 0. Two branches

- **Semaphore's repository branch** only decides which version of `e2e.yml`
  Semaphore runs. Until the playbook is on `main`, set it to a branch that has
  it (`claude/repo-structure-review-glhxab`); afterwards `main`.
- **`e2e_branch`** decides what is tested: victor's `~/WhaP` checks it out
  (`main` by default). Choose another one per run in the survey (step 4), or
  for every run in the variable group (step 3). The rig's WhaP must have been
  deployed from the same commit, or the run stops before testing.

### 1. A key for Semaphore to log in to victor

On victor, as the user who runs the tests:

```bash
ssh-keygen -t ed25519 -N "" -C semaphore-whap-e2e -f ~/.ssh/semaphore_whap_e2e
cat ~/.ssh/semaphore_whap_e2e.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/semaphore_whap_e2e    # copy this private key into Semaphore (next step) ...
rm ~/.ssh/semaphore_whap_e2e     # ... then delete it here
```

In Semaphore: **Key Store → New Key**

- Key Name: *victor e2e*
- Type: **SSH Key**
- Username: the test user (e.g. `pina`)
- Private Key: paste it

### 2. The inventory

**Inventory → New Inventory**

- Name: *WhaP e2e rig*
- User Credentials: *victor e2e*
- Type: **Static YAML**
- Content: `inventory.example.yml` from this directory, with victor's address and
  the test user filled in

The host must be named `victor` (or give the template the extra variable
`e2e_host` with its name). If Semaphore runs in a Docker container on victor,
use victor's LAN address: inside the container `localhost` is the container.

### 3. The variable group

**Variable Groups → New Group** (Semaphore requires one per template)

- Name: *WhaP e2e*
- Extra variables: `{}` uses the defaults. To change one for every run, e.g.
  `{"e2e_build_images_on": "tycho"}`. The variables:

  | Variable | Default | |
  |---|---|---|
  | `e2e_branch` | `main` | the branch to test; `""` keeps the one `~/WhaP` is on |
  | `e2e_update` | `true` | `false`: don't fetch, test the local branch as it is |
  | `e2e_pytest_args` | `""` | e.g. `--matrix full`, `--force-reset` |
  | `e2e_whap_dir` | `/docker/whap/WhaP` | the rig's WhaP, whose commit must match |
  | `e2e_allow_version_mismatch` | `false` | `true`: test even if the commits differ |
  | `e2e_build_images_on` | `tycho` | `""` skips building the images |
  | `e2e_repo_dir` | `~/WhaP` | the checkout with `whap/e2e/rig.toml` |
  | `e2e_results` | `~/whap-e2e-results` | |

### 4. The task template

**Task Templates → New Template → Ansible Playbook**

- Name: *WhaP end-to-end tests*
- Playbook Filename: `whap/e2e/ci/e2e.yml`
- Inventory: *WhaP e2e rig*
- Repository: the WhaP repository
- Variable Group: *WhaP e2e*
- Survey Variables, so each run can ask for them (both optional, type String):
  - `e2e_pytest_args`, description *pytest arguments, e.g. --matrix full*
  - `e2e_branch`, description *branch to test (empty: main)*

A survey variable left empty is not passed, so the default applies (`main`).

Save, then **Run**. The log shows the branch and commit under test, the image builds,
then nothing for the 20 minutes or more the suite takes, then the result:

```
TASK [Result]
ok: [victor] => {
    "msg": [
        "whap e2e: exit 0: == 89 passed in 1319.15s == (results in /home/pina/whap-e2e-results/2026-10-19_0200)"
    ]
}
```

A failed run lists the failed tests and ends with the task failed. Everything
about each failure (traces, screenshots, job and docker logs) is in that
results directory on victor.

### 5. Nightly

In the template: **Schedule** (or **Schedules → New Schedule**), cron
`0 2 * * *`. If the systemd timer from the runbook is enabled, disable it, or the
suite runs twice a night:

```bash
systemctl --user disable --now whap-e2e.timer
```

If Semaphore deploys the rig's WhaP as well, schedule that deploy before the
tests (e.g. `30 1 * * *`). To hear about failed runs, tick **Alert** in the
template and set up an alert channel (email, Telegram, ...) for the project.

## When the task fails before the tests

| Message | Cause |
|---|---|
| `Could not find or access 'whap/e2e/ci/e2e.yml'` | The repository's branch doesn't have the playbook (step 0). |
| `Permission denied (publickey)` | The key isn't in the test user's `~/.ssh/authorized_keys`, or the inventory's `ansible_user` is another user. |
| `Host key verification failed` | The inventory lacks `ansible_ssh_common_args`. |
| `Connection refused` / `timed out` | `ansible_host` isn't an address Semaphore reaches victor at (step 2). |
| `The tests are <branch> at <commit>, but the rig's WhaP ... runs <commit>` | Deploy that branch to the rig first. The deploy's own check makes sure victor's `/docker/whap/WhaP` and your roles match. |
| `pathspec '<branch>' did not match` | No such branch on GitHub. |
| `Not possible to fast-forward` / `Your local changes ... would be overwritten` | `~/WhaP` has local commits or changes on that branch: `git -C ~/WhaP status`. |
| `permission denied while trying to connect to the Docker daemon socket` | The test user isn't in the `docker` group. |
| `uv: command not found` | uv isn't in `~/.local/bin`, `/usr/local/bin` or `/usr/bin` on victor. |
| `Building the images failed` | The last lines of `flask build-images` follow; see the main README, "Container images and the registry". |
