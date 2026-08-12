# Fischer's Whale Pond

Whale Pond is a graphical interface designed to conveniently and quickly launch containers on the compute servers of Prof. Dr. Asja Fischer’s "Machine Learning" research group. These containers serve as working environments for computational experiments, providing access to the CPUs and GPUs of the compute servers.

Because the environments are isolated, users can have root privileges and install additional software independently. This avoids version conflicts and allows for pre-configured images where the most important software packages are already installed.

## Quick Start

1. Log in with your RUB-ID (Pina manages the LDAP group for access).
2. Add your SSH public key to allow passwordless login via SSH.
3. Create a project in the Projects tab (each project is also a folder on the storage server).
4. Start a container (select Project, Server, Image, and GPUs).

Clicking the Start button triggers Whale Pond to use Ansible to create the necessary directories, load the Docker image, and finally start the container. This process takes a few seconds, and the interface displays the live status messages from the Ansible playbook. Once the container is ready to be used, the status changes to "RUNNING," and you can log in using the displayed SSH command.

## FAQ

*Is my data lost if I stop the container?*

No. A `local_` container retains data on the compute server's local SSD until the date specified in `ttl.txt`. A `synced_` container always synchronizes all data via NFS to the storage server, where it is not automatically deleted.

*How do I back up data in a local_ container?*

`local_` containers utilize the compute server's local SSD, which is significantly faster than the NFS connection to the storage server. However, they always mount a `synced/` folder in the home directory, which synchronizes to the project directory on the storage server via NFS. It is recommended to regularly back up code and snapshots to this folder, for example, using `rsync` or backup software.