# compose-hull
Underlying Ansible role for Docker containers


merges variables from four sources:
  - service_base_defaults: defined in this role (compose_hull)
  - service_defaults: defined in the particular service role
  - service_defaults_all: defined top-level
  - service_cfg: defined in the playbook


## service_cfg variables

 * `name`
 * `directory`: the directory under which all the configuration etc. of 
   the service will be stored.  
 * `owner`: name of the user that should own the service directories
 * `create_dirs`: list of (sub-)directories to create for the service
 * `port`: port of the service (in the container)
 * `domain`: the domain of the service. e.g. 'myservice.example.com'
 * `external`: whether the service should be externally accessible (or only from within the local network)
 * `traefik`: whether to use traefik
 * `watchtower`: whether to use watchtower
 * `autoheal`: whether to use autoheal
 * `router_entry_point`: a traefik label selecting either `web-secure` (default, TLS port 443) or `web` (insecure HTTP port 80) 
 * `url_path_prefix`: if supplied traefik matches the given path prefix in the URL (the web service has to support the URL with this path)


## Tags
 * `started`
 * `restarted`
 * `recreated`
 * `stopped`
 * `absent`
