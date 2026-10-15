import yaml
import os
from typing import List
from flask import current_app, has_app_context


def _docker_registry() -> str:
    """Registry prefix for image names. Empty means locally-built images."""
    if has_app_context():
        value = current_app.config.get("DOCKER_REGISTRY", "")
    else:
        value = os.environ.get("DOCKER_REGISTRY", "")
    return (value or "").rstrip("/")


# Roles whose image is the same for every user: the entrypoint sets the user up
# when the container starts. Their compose file names <type>_<system>:<tag>,
# from DOCKER_REGISTRY if set; the tag is the hash of the role's build files
# (images.image_tag). Other roles (custom ones elsewhere in ANSIBLE_ROLES_PATH)
# build an image per user.
SHARED_IMAGE_ROLES = {
    "worker_synced_ubuntu2404_ssh", "worker_local_ubuntu2404_ssh",
    "worker_synced_ubuntu2504_ssh", "worker_local_ubuntu2504_ssh",
    "worker_synced_ubuntu2510_ssh", "worker_local_ubuntu2510_ssh",
    "worker_synced_ubuntu2604_ssh", "worker_local_ubuntu2604_ssh",
    "worker_local_cuda-11-7_ubuntu2204_ssh", "worker_synced_nvidia_pytorch1906",
}


def build_compose_file(container_name: str,
                       role_name: str,
                       user: str,
                       user_id: int,
                       group_id: int,
                       password: str,
                       project_name: str,
                       mac_address: str,
                       network_name: str,
                       ipv4_address: str,
                       additional_volumes: List = (),
                       additional_gids: List = (),
                       cpu_limit: float = None,
                       gpu_selection: List = (),
                       image_tag: str = "latest") -> str:
    _, container_type, system = role_name.split('_', 2)
    registry_container: bool = role_name in SHARED_IMAGE_ROLES
    container_config = {
        "runtime": "nvidia",
        "ipc": "host",
        "container_name": container_name,
        "restart": "unless-stopped",
        "ports": ["22:22"],
        "volumes": [],
        "environment": ["PROJECT=" + project_name, "SAFE_PROJECT_NAME=" + project_name],
        "mac_address": mac_address,
        "networks": {network_name: {"ipv4_address": ipv4_address}},
        "labels": ["com.centurylinklabs.watchtower.enable=false"],
        "healthcheck": {
            "test": ["CMD-SHELL", r'netstat -nlp | grep -E ":22\s+\S*\s+LISTEN\s+\S*sshd" > /dev/null'],
            "interval": "5s",
            "timeout": "5s",
            "retries": "5"
        }
    }
    if container_type == "synced":
        container_config["volumes"].append("/data/" + user + "/" + project_name + "/:/home/" + user + ":rw")
    elif container_type == "local":
        container_config["volumes"].append("/home/" + user + "/" + project_name + "/:/home/" + user + ":rw")
        container_config["volumes"].append("/data/" + user + "/" + project_name + "/:/home/" + user + "/synced:rw")
    for additional_volume in additional_volumes:
        container_config["volumes"].append(additional_volume)
    if registry_container:
        registry = _docker_registry()
        image = f"{container_type}_{system}:{image_tag}"
        container_config["image"] = f"{registry}/{image}" if registry else image
        container_config["environment"].append("USERNAME=" + user)
        container_config["environment"].append("USER_ID=" + str(user_id))
        container_config["environment"].append("GROUP_ID=" + str(group_id))
        container_config["environment"].append("PASSWORD_FILE=/run/secrets/user_password_file")
        container_config["environment"].append("ADDITIONAL_GIDS=" + ','.join([str(ag) for ag in additional_gids]))
        container_config["secrets"] = [{
            "source": "user_password",
            "target": "user_password_file"
        }]
    else:
        container_config["build"] = {
            "context": "/docker/" + role_name + "-" + user + "-" + project_name + "/build/",
            "dockerfile": "Dockerfile",
            "args": {
                "USERNAME": user,
                "USER_ID": str(user_id),
                "GROUP_ID": str(group_id),
                "PASSWORD": password,
                "USER_COMMENT": user
            }
        }
    if cpu_limit is not None or len(gpu_selection) > 0:
        container_config["deploy"] = {"resources": {}}
    if cpu_limit is not None:
        container_config["deploy"]["resources"]["limits"] = {"cpus": cpu_limit}
    if len(gpu_selection) > 0:
        container_config["deploy"]["resources"]["reservations"] = {"devices": [{
            "driver": "nvidia",
            "device_ids": gpu_selection,
            "capabilities": ["compute", "utility"]
        }]}
    compose_content = {
        "name": container_name,
        "services": {
            container_name: container_config
        },
        "networks": {network_name: {"external": True}}
    }
    if registry_container:
        compose_content["secrets"] = {
            "user_password": {"file": "./secret_password.txt"}
        }
    return yaml.dump(compose_content, default_style='"')
