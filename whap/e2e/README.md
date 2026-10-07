# End-to-end tests

Browser-driven tests that run against a real WhaP deployment: a storage server
running the application and a compute server with a GPU. They drive the
frontend the way a person would, through the `data-testid` attributes described
in the top-level README.

Run the tests from a machine on the compute server's container network, but
not from the compute server itself. Containers get their own address on a
macvlan network and are reached over SSH at that address; Linux does not let a
host talk to its own macvlan children, so from tycho they are unreachable.
The storage server is the natural place.

## Running the tests

Deploy the rig with the fixtures enabled (below), then, in this directory:

```bash
cp rig.example.toml rig.toml      # describe the rig: URL, passwords, paths
cp seed.example.yml seed.yml      # the rig's server, network and addresses
uv sync
uv run playwright install chromium   # or set [browser] executable in rig.toml
uv run pytest
```

Every session starts by resetting the rig and seeding it (see "Seeding the
rig"), so runs don't depend on each other. If a previous run left containers
behind, the session stops and lists them; delete them in WhaP, or run with
`--force-reset` to drop their records. Use `--rig=PATH` (with the `=`: a bare
path argument makes pytest look for its configuration there) or `WHAP_E2E_RIG`
to point at another rig file, `--headed` to watch the browser, and
`--matrix full` to run the container matrix on every role (below).

The modules run in phase order -- identity, one container's lifecycle, then
the matrix -- whatever their file names, so a broken login fails fast.

### What a failure leaves behind

Everything lands in `test-results/` (pytest's `--output`), so a failure can be
understood without running the suite again:

- a Playwright trace of every browser context the failed test used --
  pytest-playwright's own, and the ones the harness opens for `login` and for
  each container (`evidence.py`). Open one with
  `uv run playwright show-trace <file>`. The harness's traces hold DOM
  snapshots but no screencast, which would add tens of MB per container.
- if the test had a container: a screenshot, the container's whole job log
  (`job.log`), and its `docker inspect` state and `docker logs` from the
  compute server (`docker.log`). The last lines of each are also in the
  report. `docker.log` needs `[compute] shell` in rig.toml, e.g.
  `["ssh", "tycho"]`, as a user with docker access.

### What runs today

`tests/test_identity.py` covers what a user does before starting a
container, in about 15 seconds:

- signing in through LDAP (and that it is an LDAP session), signing out, and
  being refused with a wrong password
- adding an SSH key, which survives a reload byte for byte
- creating a project, and the worker creating its directory on the storage
  server, owned by the user's LDAP uid and gid and group-writable (`2775`)
- sharing a project with another user found through the LDAP user search, and
  that share and the e2e dataset being offered as volumes

`tests/test_container_lifecycle.py` takes one container through its life. It
creates it through the form with an SSH key, a password and one GPU, using the
role set as `[container] image` in rig.toml, and records how it comes up. Then,
one test per point:

- the Ansible log reaches the browser as a stream -- Socket.IO frames
  arriving over time, the log pane visibly growing -- and the end of the job is
  announced only after its last line
- reloading the page mid-job replays the log so far, then continues live
- the container reaches RUNNING, and its card shows the right `ssh` command
- the user can log in with the key and, separately, with the password, as
  their LDAP uid and gid
- `nvidia-smi` sees exactly the requested GPU, by name
- `nvtop` and `tmux` run, and a virtualenv can be made with pip in it
- PyTorch multiplies a matrix on that GPU
- deleting the container in the UI removes it and frees its address

If the container doesn't reach RUNNING, that test fails with the tail of its
log and the tests that need a running container are skipped. Another test
checks that the container password appears nowhere the browser can see: the
stored log, the log pane, or any Socket.IO frame.

PyTorch is installed with pip into `~/.e2e-venv` in the container. The project
is always called `e2e-gpu`, and for local roles its home directory lives on the
compute server, which reset leaves alone, so the multi-gigabyte download happens
once per rig. Set `[torch] index_url` to a CUDA build the server's driver
supports. The first container of a role may also build or pull its image: allow
for it in `[container] start_timeout`.

`tests/test_container_matrix.py` covers how a user gets into a container,
what it can mount, and every role. Each case is one container, started through
the form and deleted before the next starts:

| Case       | Roles                       | Logs in with     | Volumes                                    | Checks                                                                 |
|------------|-----------------------------|------------------|--------------------------------------------|------------------------------------------------------------------------|
| `key`      | `[container] image`         | SSH key          | the e2e dataset, a project bob shares `ro` | key login; dataset marker readable; neither volume writable            |
| `password` | `[container] image`         | password         | a project bob shares `rw`                  | password login; the key is refused; alice's file lands in bob's project on the storage server, owned by her |
| `both`     | every other `worker_` role  | key and password | --                                         | both logins; `nvidia-smi` sees the GPU; `nvtop`, `tmux` and a virtualenv work; the image does what it is for |

`--matrix full` also runs `key` and `password` on every role. `[container]
image` gets no `both` case: the lifecycle module covers it. `worker_ollama` is
left out; it serves an HTTP API rather than SSH logins. One more test needs no
case: the form refuses a container with neither key nor password, as does the
API.

"What it is for" is `PURPOSE` in the module: the NGC image's PyTorch computes
on the GPU, the CUDA 11.7 image has `nvcc` 11.7. The NGC image has no `nvtop`
(its Ubuntu 18.04 base has no package); `MISSING_TOOLS` in `containers.py`
records that, so the check skips it rather than fail every run.

With nine roles, a first run on a fresh rig builds nine images; allow for it
in `[container] start_timeout`, which applies to each container.

Project directories are created `2775`, so a project shared read-write is
writable by everyone it is shared with (their containers get the directory's
group). `test_identity.py` checks the mode; the `password` case checks alice
can write.

An SSH key, once deployed, stays in `~/.ssh/authorized_keys` in the project's
home, so later containers in the same project accept it too; that is
intended, and not tested.

Tests address the UI through page objects in `pages/`, never through selectors,
so a frontend change touches only that package. `remote.py` logs into
containers over SSH, accepting their host keys -- each test container is new.

## Nightly runs

`nightly/run.sh` runs the suite once, unattended, into a dated directory under
`$WHAP_E2E_RESULTS` (default `~/whap-e2e-results`): `pytest.log`, `junit.xml`,
`summary.txt` (pytest's last line) and `test-results/`. `latest` points at the
newest run, and runs older than `$WHAP_E2E_KEEP_DAYS` (14) are removed. It exits
with pytest's status; arguments are passed to pytest.

To run it every night on the storage server, as the user that has the
repository checked out (with rig.toml and seed.yml filled in):

```bash
mkdir -p ~/.config/systemd/user
cp nightly/whap-e2e.service nightly/whap-e2e.timer ~/.config/systemd/user/
# edit WHAP_REPO in whap-e2e.service if the checkout is not ~/WhaP
systemctl --user daemon-reload
systemctl --user enable --now whap-e2e.timer
sudo loginctl enable-linger "$USER"     # run while nobody is logged in
```

The timer fires at 01:17 and catches up on a missed night. A run is a
`oneshot` service, so `systemctl --user status whap-e2e` shows the last
result and `journalctl --user -u whap-e2e` its one-line summary. If a run
leaves containers behind, the next one stops at reset and says so; that is
deliberate, since dropping their records would orphan them on the compute
server. Add an `OnFailure=` unit if you want to be told by mail.

## LDAP directory

`ldap/` builds a disposable OpenLDAP directory with two people:

| uid         | uidNumber | Role in the tests                                  |
|-------------|-----------|----------------------------------------------------|
| `e2e-alice` | 70001     | The user under test                                |
| `e2e-bob`   | 70002     | Owns a project shared with alice, for volume tests |

Both have `gidNumber` 70000, `objectClass: inetOrgPerson` and `posixAccount`,
and live under `ou=people,dc=whap,dc=test`. WhaP searches as
`cn=whap-bind,dc=whap,dc=test`; anonymous reads are refused, as against a real
directory. The ids are high so they don't collide with real accounts on the
compute servers, where they become the in-container user and own files on the
host.

The directory is initialised on first start and kept across restarts.
Recreating the container (`docker compose up -d --force-recreate e2e-ldap`)
resets it.

## Seeding the rig

The servers, the container network, its address pool and the test users'
permissions are rows in WhaP's database. Copy `seed.example.yml`, fill in your
rig's values, and load it from the storage server:

```bash
docker exec -i whap-backend flask e2e-seed - < seed.yml
```

Seeding is idempotent: it creates what is missing and updates the rest to match
the file. It never takes over rows it does not own, so an address that already
belongs to another network is reported, not moved.

Before each run, clear what the previous one left behind:

```bash
docker exec -i whap-backend flask e2e-reset - < seed.yml
```

This removes the test users' projects (and queues deletion of their
directories), shares, SSH keys, the groups they made, and their other group
memberships. It keeps the seeded infrastructure. If the test users still have
containers it stops and lists them: deleting only the database record would
orphan a container still running on the compute server, so delete them through
WhaP, or pass `--force` to drop the records anyway. `--all` removes the seeded
group, addresses, network and servers as well, except a server other groups
still use. `--keep-project-dirs` leaves the directories in place.

Both commands refuse to run unless the rig was deployed with the `e2e` switch,
because reset deletes the listed users' data.

## Dataset

The `whap` role creates `DATASETS/e2e-dataset/e2e-marker.txt` (content
`whap-e2e-dataset`) on the storage server, so the tests can mount a dataset and
read a known file back. It is made by Ansible on the host because every WhaP
container mounts `DATASETS` read-only: datasets are curated by an admin, not by
the application.

## Enabling the fixtures on a test rig

In the storage server's host_vars, switch the rig into test mode and point WhaP
at the test directory:

```yaml
whap:
  # ...
  e2e:
    enabled: true
    ldap_admin_password: "..."
    alice_password: "..."
    bob_password: "..."

ldap:
  uri: "ldap://e2e-ldap"
  base:
    dn: "ou=people,dc=whap,dc=test"
  binduser:
    dn: "cn=whap-bind,dc=whap,dc=test"
    password: "..."          # the directory is seeded with this
  user_object_class: "inetOrgPerson"
```

Plain `ldap://` is deliberate: the directory has no certificate, and traffic
never leaves the compose network, which publishes no LDAP port. Never enable
`e2e` on a production server.

### Running it on its own

```bash
docker build -t whap-e2e-ldap whap/e2e/ldap
docker run --rm -p 127.0.0.1:3890:389 \
  -e LDAP_ADMIN_PASSWORD=admin -e LDAP_BIND_PASSWORD=bind \
  -e E2E_ALICE_PASSWORD=alice -e E2E_BOB_PASSWORD=bob \
  whap-e2e-ldap
ldapwhoami -x -H ldap://localhost:3890 -D uid=e2e-alice,ou=people,dc=whap,dc=test -w alice
```
