#!/bin/sh
# Disposable LDAP directory for WhaP's end-to-end tests.
#
# On first start, builds an OpenLDAP configuration and a small directory:
#
#   dc=whap,dc=test
#   ├── cn=whap-bind            service account WhaP searches with
#   └── ou=people               LDAP_USER_BASE_DN
#       ├── uid=e2e-alice       uidNumber 70001, the user under test
#       └── uid=e2e-bob         uidNumber 70002, owns the project shared with alice
#
# Both people are inetOrgPerson + posixAccount with gidNumber 70000. The high
# ids keep them clear of real accounts on the compute servers, where they
# become the in-container user and own files on the host.
#
# Only the passwords are configurable, and all four are required, so no
# credentials live in the repository. Anonymous reads are refused, so WhaP's
# service-account bind is exercised exactly as against a real directory.
set -eu

: "${LDAP_ADMIN_PASSWORD:?must be set}"
: "${LDAP_BIND_PASSWORD:?must be set (the password WhaP binds with)}"
: "${E2E_ALICE_PASSWORD:?must be set}"
: "${E2E_BOB_PASSWORD:?must be set}"

BASE_DN="dc=whap,dc=test"
CONF_DIR=/etc/ldap/slapd.d
DATA_DIR=/var/lib/ldap
MARKER="$DATA_DIR/.whap-e2e-initialized"

hash() { slappasswd -h '{SSHA}' -s "$1"; }

person() {  # uid uidNumber password
    cat <<EOF
dn: uid=$1,ou=people,$BASE_DN
objectClass: inetOrgPerson
objectClass: posixAccount
uid: $1
cn: $1
sn: $1
mail: $1@whap.test
uidNumber: $2
gidNumber: 70000
homeDirectory: /home/$1
loginShell: /bin/bash
userPassword: $(hash "$3")

EOF
}

if [ ! -f "$MARKER" ]; then
    echo "Initialising the e2e directory under $BASE_DN"
    rm -rf "${CONF_DIR:?}"/* "${DATA_DIR:?}"/*

    slapadd -n 0 -F "$CONF_DIR" <<EOF
dn: cn=config
objectClass: olcGlobal
cn: config
olcPidFile: /run/slapd/slapd.pid

dn: cn=module{0},cn=config
objectClass: olcModuleList
cn: module{0}
olcModulePath: /usr/lib/ldap
olcModuleLoad: back_mdb

dn: cn=schema,cn=config
objectClass: olcSchemaConfig
cn: schema

include: file:///etc/ldap/schema/core.ldif
include: file:///etc/ldap/schema/cosine.ldif
include: file:///etc/ldap/schema/nis.ldif
include: file:///etc/ldap/schema/inetorgperson.ldif

dn: olcDatabase={-1}frontend,cn=config
objectClass: olcDatabaseConfig
objectClass: olcFrontendConfig
olcDatabase: {-1}frontend

dn: olcDatabase={0}config,cn=config
objectClass: olcDatabaseConfig
olcDatabase: {0}config

dn: olcDatabase={1}mdb,cn=config
objectClass: olcDatabaseConfig
objectClass: olcMdbConfig
olcDatabase: {1}mdb
olcDbDirectory: $DATA_DIR
olcSuffix: $BASE_DN
olcRootDN: cn=admin,$BASE_DN
olcRootPW: $(hash "$LDAP_ADMIN_PASSWORD")
olcDbIndex: objectClass eq
olcDbIndex: uid eq
olcAccess: {0}to attrs=userPassword by self write by anonymous auth by * none
olcAccess: {1}to * by users read by * none
EOF

    { cat <<EOF
dn: $BASE_DN
objectClass: dcObject
objectClass: organization
dc: whap
o: WhaP end-to-end tests

dn: ou=people,$BASE_DN
objectClass: organizationalUnit
ou: people

dn: cn=whap-bind,$BASE_DN
objectClass: simpleSecurityObject
objectClass: organizationalRole
cn: whap-bind
userPassword: $(hash "$LDAP_BIND_PASSWORD")

EOF
      person e2e-alice 70001 "$E2E_ALICE_PASSWORD"
      person e2e-bob 70002 "$E2E_BOB_PASSWORD"
    } | slapadd -n 1 -F "$CONF_DIR"

    touch "$MARKER"
fi

mkdir -p /run/slapd
chown -R openldap:openldap "$CONF_DIR" "$DATA_DIR" /run/slapd

# -d keeps slapd in the foreground as PID 1; "stats" logs every bind and
# search, which is what you want when an e2e login fails.
exec slapd -h "ldap:///" -u openldap -g openldap -F "$CONF_DIR" -d "${LDAP_LOG_LEVEL:-stats}"
