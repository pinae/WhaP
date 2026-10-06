# End-to-end tests

Browser-driven tests that run against a real WhaP deployment: a storage server
running the application and a compute server with a GPU. They drive the
frontend the way a person would, through the `data-testid` attributes described
in the top-level README.

This directory currently holds the test rig's fixtures. The test suite itself
follows.

Run the tests from a machine on the compute server's container network, but
not from the compute server itself. Containers get their own address on a
macvlan network and are reached over SSH at that address; Linux does not let a
host talk to its own macvlan children, so from tycho they are unreachable.
The storage server is the natural place.

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
