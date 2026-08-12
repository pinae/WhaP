#!/usr/bin/python

# Copyright: (c) 2024, Pina Merkert <pina@pinae.net>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import (absolute_import, division, print_function)
from ansible.module_utils.basic import AnsibleModule
__metaclass__ = type

DOCUMENTATION = r'''
---
module: traefik_info_facts

short_description: This module builds strings for the traefik configuration

version_added: "1.0.0"

description: This module builds a facts for the traefik configuration. The domain rule is used for the routers rule.
In the list middleware_config_lines the middleware configurations are collected. The middleswares are activated by
stating them in the comma separated list of the middlewares string in the return values of this task.

options:
    service_name:
        description: The name of the service configured.
        required: true
        type: str
    domains:
        description: A single string of a (sub)domain for the service or a list of domains.
        required: true
        type: str or list
    path_prefix:
        description: If the service lives at a sub path set this parameter. The path is prefixed to all urls for this service and traefik will test for that. This param is useful for running multiple services at the same domain.
        required: false
        type: str
    stripprefix:
        description: This may activate a middleware which strips the prefixed path. Default: False
        required: false
        type: bool
    external:
        description: This option is used to disable external access to the service. Trafik will filter for internal IPs. Default: True
        required: false
        type: bool
    ip_whitelist:
        description: If you want to filter for internal IPs you have to supply the list of allowed IPs here. Default: empty list
        required: false
        type: list

author:
    - Pina Merkert (@pinae)
'''

EXAMPLES = r'''
# Simple domain
- name: Simple subdomain
  my_namespace.my_collection.traefik_info_facts:
    service_name: "portainer"
    domain: "portainer.example.com"

# Internal service
- name: Test with a message and changed output
  my_namespace.my_collection.traefik_info_facts:
    service_name: "smarthome_service"
    domain: "my.dyndns.domain.example.com"
    external: false
    ip_whitelist:
      - 192.168.0.0/16
      - 10.0.0.0/8
    path_prefix: "/smarthome_service"
    stripprefix: true
'''

RETURN = r'''
# These are examples of possible return values, and in general should use other names for return values.
domain_rule:
    description: A rule string for the router configuration in the correct format to be used as a docker label.
    type: str
    returned: always
    sample: '(Host(`example.com`) && PathPrefix(`/foo/bar`) && (ClientIP(`192.168.111.2/16`) || ClientIP(`10.0.0.0/8`))) || (Host(`www.example.com`) && PathPrefix(`/foo/bar`) && (ClientIP(`192.168.111.2/16`) || ClientIP(`10.0.0.0/8`)))'
middleware_config_lines:
    description: A list of config lines for middlewares if they need them.
    type: list
    returned: always
    sample: '[
            "traefik.http.middlewares.example_com_stripprefix.stripprefix.prefixes: \"/foo/bar\""
        ]'
middlewares:
    description: The comma separated list of active middlewares.
    type: str
    returned: always
    sample: 'internal-ips-only@file,example_com_stripprefix'
'''


def run_module():
    module_args = dict(
        service_name=dict(type='str', required=True),
        domains=dict(type='list', required=True),
        path_prefix=dict(type='str', required=False, default=""),
        stripprefix=dict(type='bool', required=False, default=False),
        external=dict(type='bool', required=False, default=True),
        ip_whitelist=dict(type='list', required=False, default=[])
    )

    result = dict(
        changed=True,
        domain_rule='',
        middleware_config_lines=[],
        middlewares=''
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    domains = [module.params['domains']] if type(module.params['domains']) is str else module.params['domains']

    domain_rules = []
    for domain in domains:
        domain_rule = "Host(`{}`)".format(domain)
        rules = [domain_rule]
        if len(module.params['path_prefix']) > 0:
            rules.append("PathPrefix(`{}`)".format(module.params['path_prefix']))
        if len(module.params['ip_whitelist']) > 0:
            ip_whitelist = " || ".join(["ClientIP(`{}`)".format(i) for i in module.params['ip_whitelist']])
            rules.append("(" + ip_whitelist + ")")
        if len(rules) == 1:
            domain_rules.append(domain_rule)
        else:
            domain_rules.append("(" + " && ".join(rules) + ")")
    result['domain_rule'] = " || ".join(domain_rules)

    middlewares = []
    if not module.params['external']:
        middlewares.append('internal-ips-only@file')
    if module.params['stripprefix'] and len(module.params['path_prefix']) > 0:
        middlewares.append(module.params['service_name'] + '_stripprefix')
        result['middleware_config_lines'].append("traefik.http.middlewares.{}.stripprefix.prefixes: \"{}\"".format(
            module.params['service_name'] + '_stripprefix',
            module.params['path_prefix']))
    result['middlewares'] = ",".join(middlewares)

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
