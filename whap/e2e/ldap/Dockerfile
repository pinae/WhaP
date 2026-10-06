# Disposable LDAP directory for WhaP's end-to-end tests. See entrypoint.sh for
# what it contains. Built on Debian's own slapd rather than a third-party
# OpenLDAP image: osixia/openldap is unmaintained, and Bitnami withdrew its
# free images. Same Debian release as the backend image.
FROM debian:trixie-slim

# The package's postinst creates a default dc=nodomain database; remove it so
# the entrypoint starts from nothing.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils \
    && rm -rf /var/lib/apt/lists/* /etc/ldap/slapd.d/* /var/lib/ldap/*

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

EXPOSE 389

# Healthy once the service account WhaP uses can actually bind.
HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
    CMD ldapwhoami -x -H ldap://localhost -D "cn=whap-bind,dc=whap,dc=test" -w "$LDAP_BIND_PASSWORD"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
