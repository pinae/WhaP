# Running the end-to-end tests on victor and tycho

A checklist for the first run. The background to every step is in
[README.md](README.md); this is just the order to do things in.

**victor** is the storage server: it runs WhaP and, from now on, the tests.
**tycho** is the compute server with the RTX 2070 Super. The tests run on
victor because containers get their own address on tycho's LAN (macvlan), and
tycho itself cannot reach them.

> **This turns victor's WhaP into a test deployment.** Enabling the fixtures
> points WhaP at a throwaway LDAP directory, and every run deletes the test
> users' projects. Never do this to the production instance.

## 1. Deploy the test branch with the fixtures on

Everything the tests need is on the branch `claude/repo-structure-review-glhxab`,
not yet on `main`. It must be checked out in **two** places:

- **Your private config repository's `WhaP` submodule**, wherever you run
  `ansible-playbook`. This supplies the roles.
- **`/docker/whap/WhaP` on victor**, i.e. `whap.directory`/`app_subdir`. The
  role builds the backend and frontend images from this checkout, and nothing
  updates it for you. The playbook stops if the two are at different
  commits: the roles would render a compose file for one version while
  the images are built from the other.

```bash
git -C WhaP fetch origin claude/repo-structure-review-glhxab              # in the config repo
git -C WhaP checkout claude/repo-structure-review-glhxab

git -C /docker/whap/WhaP fetch origin claude/repo-structure-review-glhxab  # on victor
git -C /docker/whap/WhaP checkout claude/repo-structure-review-glhxab
git -C /docker/whap/WhaP pull
```

In victor's host_vars, switch on the fixtures. Pick three passwords:

```yaml
whap:
  # ...
  e2e:
    enabled: true
    ldap_admin_password: "..."
    alice_password: "..."      # goes into rig.toml later
    bob_password: "..."        # goes into rig.toml later
```

That is all: with `e2e.enabled` the role points WhaP at the test directory
(`ldap://e2e-ldap`) by itself. The `ldap` block stays as it is and is used
again once `e2e` is off. Meanwhile real users cannot sign in. The directory's
service account uses `ldap.binduser.password` unless you set
`e2e.bind_password`.

Then deploy both machines. tycho gets the new worker images (python3-venv,
tmux) and role changes:

```bash
ansible-playbook plays/whap.yml
```

Check that it worked:

- `docker ps` on victor lists `whap-e2e-ldap` next to `whap-backend` and `whap-worker`.
- `docker exec whap-backend flask --help` lists `e2e-seed` and `e2e-reset`.
  If they are missing, the backend runs old code:
  - Check `git -C /docker/whap/WhaP log --oneline -1`; it should match this
    branch's latest commit.
  - Check that `docker images whap-backend` shows an image created by this
    deploy.
- The backend logs no `ANSIBLE_RUNNER_DIR not configured` at start
  (`docker logs whap-backend | head`). That warning means an old image.
- The backend answers:
  `curl -s https://<your WhaP domain>/auth/session` prints `{"isLoggedIn":false,...}`
  at once. If it hangs, or `docker ps` shows `whap-backend` restarting,
  `docker logs whap-backend` names the configuration problem.
- On tycho, Docker can use the GPU:
  `docker run --rm --gpus all ubuntu nvidia-smi` shows the 2070 Super.
- If you use the registry for the 2510 roles, its images are pushed.
  Otherwise tycho has nothing to pull.

## 2. Prepare victor to run the tests

On victor, as the user who will run them, clone the same branch somewhere
outside the deployment. The tests must match what is deployed:

```bash
git clone -b claude/repo-structure-review-glhxab https://github.com/pinae/WhaP.git ~/WhaP
cd ~/WhaP/whap/e2e
curl -LsSf https://astral.sh/uv/install.sh | sh     # if uv is missing
uv sync
uv run playwright install --with-deps chromium     # asks for sudo for the system libraries
```

That user also needs:

- **docker access on victor** (the `docker` group), for `docker exec whap-backend flask ...`.
- **SSH to tycho with a key, as a user in tycho's `docker` group.** This is
  optional: it attaches `docker logs` to failures. Test it with
  `ssh tycho docker ps`.

## 3. Describe the rig

```bash
cp rig.example.toml rig.toml
cp seed.example.yml seed.yml
```

In **seed.yml**:

- `servers`: `tycho` as Ansible's inventory names it, `gpu_count: 1`.
- `network`: tycho's LAN subnet, i.e. the network on its `ethernet_device`.
  The name must not end in `public`.
- `addresses`: **four free IPs on that subnet**, nothing else may use them.
  Keep the example's locally administered MACs.

In **rig.toml**:

- `[whap] url`: WhaP's address as a browser on victor reaches it.
- `[users.alice]` and `[users.bob]`: the passwords from step 1.
- `[storage]`:
  - `shell = []`, since the tests run on victor.
  - `backend_cli` as in the example.
  - `projects_dir` = `whap.projects_dir` from the host_vars, e.g. `/data/projects`.
- `[compute] shell = ["ssh", "tycho"]`, if you set up SSH in step 2.
- `[container]`:
  - `gpu_name = "2070"`
  - `start_timeout = 3600` for the first run, because every image builds once.
- `[torch] index_url`: a CUDA build tycho's driver supports.
  `nvidia-smi` on tycho shows "CUDA Version: 12.x"; e.g. `https://download.pytorch.org/whl/cu126`.

## 4. Run it, cheapest first

Each step only makes sense once the previous one passes.

```bash
cd ~/WhaP/whap/e2e
uv run pytest tests/test_identity.py            # under a minute: LDAP, keys, projects, shares
uv run pytest tests/test_container_lifecycle.py  # one container end to end; first run builds an image and installs torch
uv run pytest                                   # everything: ~10 containers, roughly 1-2 h once images exist
uv run pytest --matrix full                     # later: auth and volume cases on every role as well
```

Every run starts by resetting and re-seeding the rig. If a run was interrupted
and left containers behind, the next one stops and lists them. Delete them in
WhaP, or add `--force-reset` if you have already removed them on tycho.

Use `--rig=PATH`, with the `=`, if rig.toml is not next to the tests. Add
`--headed` (from a desktop session) to watch the browser.

## 5. When something fails

Everything about a failure is in `test-results/`:

- `trace.zip`: open it with `uv run playwright show-trace test-results/<dir>/trace.zip`
  to step through what the browser saw.
- `job.log`: the container's whole Ansible log.
- `docker.log`: `docker inspect` and `docker logs` from tycho.
- `screenshot.png`

What to suspect first:

| Symptom | Likely cause |
|---|---|
| "No such command 'e2e-reset'", or the harness says the backend runs old code | `/docker/whap/WhaP` on victor is not on this branch, or the deploy did not rebuild `whap-backend`: see the checks in step 1 |
| The run stops at once: "GET .../auth/session failed" (the browser shows only a spinner) | the backend is not serving: `docker logs whap-backend`, usually a FATAL configuration error |
| Login tests fail with "Invalid credentials" | WhaP is not using the test directory: `docker exec whap-backend env \| grep LDAP_SERVER_URI` must say `ldap://e2e-ldap` (redeploy with `e2e.enabled`); otherwise the passwords in rig.toml differ from `e2e.alice_password`/`bob_password` |
| Container reaches RUNNING, SSH times out | the IPs in seed.yml are not reachable from victor (wrong subnet, or the tests run on tycho) |
| Container ends in ERROR | `job.log`: often an image build, a registry pull, or the GPU (nvidia-container-toolkit) |
| `test_the_compute_server_sees_the_projects_and_datasets` fails, or a share is "a placeholder Docker made" | tycho's `/data` is not victor's `projects_dir`: mount it over NFS (worker host_vars `nfs`), so that `/data/<user>/<project>` and `/data/DATASETS` on tycho are the directories on victor |
| PyTorch test fails on CUDA | `[torch] index_url` does not match the driver |
| `worker_synced_nvidia_pytorch1906` "image does what it is for" fails | expected: its conda Python is probably not on PATH in SSH sessions; please send me the output |

## 6. Nightly runs (optional, once a manual run is green)

```bash
mkdir -p ~/.config/systemd/user
cp nightly/whap-e2e.service nightly/whap-e2e.timer ~/.config/systemd/user/
# set WHAP_REPO in whap-e2e.service if the checkout is not ~/WhaP
systemctl --user daemon-reload
systemctl --user enable --now whap-e2e.timer
sudo loginctl enable-linger "$USER"
```

Results land in `~/whap-e2e-results/<date>/`, and `latest` points at the
newest. `systemctl --user status whap-e2e` shows whether the last night passed.

## 7. Afterwards

To turn victor back into a normal deployment:

1. Set `e2e.enabled: false`; WhaP uses the `ldap` block again.
2. Redeploy.

Then delete the e2e projects' directories under `projects_dir/e2e-*` on
victor, and `/home/e2e-*` on tycho, which holds the local roles' project
homes and the torch virtualenv.
