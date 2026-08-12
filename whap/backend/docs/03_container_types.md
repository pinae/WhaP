# Containers for computational experiments

For running computational experiments we have four compute servers available:
1. **cuda01**: 2x RTX 2080 Ti (12GB VRAM), 16 CPU cores, 32GB RAM
2. **cuda02**: 3x RTX 3090 (24GB VRAM), 32 CPU cores, 256GB RAM
3. **cuda03**: 4x A40 (46GB VRAM), 64 CPU cores, 512GB RAM
4. **cuda04**: 4x A40 (46GB VRAM), 64 CPU cores, 512GB RAM

Since these experiments often times depend on different versions for libraries like CUDA and PyTorch we offer separate Linux environments for each project. These environments are implemented using Docker containers and the nvidia-container-toolkit passing access to GPUs to the containers. By using the macvlan networking driver in Docker we can offer separate IP addresses for the containers which look and feel like private compute servers the user has access to. Users have root access inside these containers and can install software using standard linux packaging tools like `apt`. You can also install python packages with `pip` system wide but you don't need to and may also use virtual envionments as usual.

There are prebuilt images for different versions of Ubuntu which have CUDA and PyTorch pre installed in the versions mentioned in the image name. If in doubt use the most recent version. 

You can use one of these images and install a lot of software utilizing your root privileges. But if you are doing this a lot it might be wise to ask Pina for a new image which already includes the needed software. Container images consist of an ephemeral base system which only exists as long as the container is running combined with volumes which store everything worth keeping. It is considered good practice to have a base image containing all the software needed for running the payload of the container and storing only the data in volumes.

For monitoring the running containers and easily start new ones we have our own software called "Fischer's Whale Pond" (Whap): https://whap.storageserver.ig17s.rub.de

You can authenticate yourself at the Whale Pond using your RUB-ID if you are part of the ML-LDAP-Group. After that you may save your SSH public key there to enable passwordless login to containers. Then you create your first project and decide if you want to share your project with other users of the Whale Pond. After that you create your first container by selecting the project, the image, the compute server and which GPUs you want to use there. It depends on your group membership in the Whale Pond which images, compute servers and GPUs are available to you. Apfter you click "Start Container" you see the output of an Ansible playbook setting up the container. This usually takes a couple of seconds. After the startup script finished Whap displays the ssh command you may use to connect to the container.

## For starters: the `synced`-Containers

Users who want an easy start should use the `synced` containers. The start script automatically creates a project directory on the storage server which is available as `/home/<username>/` inside the container. All the rest of the containers linux environmenmt is ephemeral and only exists as long as the container lives (this includes software installed with `apt`). But the home directory is synced to the storage server and immediately available on all compute servers if the same project is selected while starting a container. The storage server automatically creates snapshots which offer a very similar functionality to automatic backups. 

The convenience and data security of this setup has one relevant downside: As all the data needs to be transferred over the network the read and write speed is limited by the networking (max. 115 MB/s).

## The `local`-Containers

Users who need very fast read and write operations especially for large files should use the `local` containers. Starting one of them creates a project directory on the local SSD of the compute server: `/home/<username>/<projectname>/`. This directory will be the `/home/<username>/` in the container. Similar to the `synced` containers there will also be a directory `/data/<username>/<projectname>/` which gets mounted as `/home/<username>/synced/` inside the container. This directory should be used for storing all meaningful results and probably the code because it gets synced to the storage server and benefits from the automatic creation of snapshots there.

Since the space on the local SSD is limited each project has a time to live (ttl) noted as a exiration date in the file `ttl.txt` inside the project directory. If no such file is present or if the expiration date is in the past (or invalid) the directory will automatically be deleted by the ttl daemon running on all compute servers. Whap displays the ttl date and offers a convenient button to prolong the deletion by 4 weeks. 

There is no automatic backup of local project directories. They are intended for fast execution of code, storage for ephemeral execution environments, snapshots and short lived datasets. Make sure you have scripts in place which automatically copy any data worth keeping to the `~/synced/` directory. The read and write speed there will be limited by 1GB networking which results in an upper limit of 115 MB/s. It might be a good idea to have compute code use the fast local storage and run a separate process simultaneously which copies precious data in a non blocking way.

## Working bare-metal

There is the option to work bare metal on the host system. However this is only advisable for very experienced users as you need to make sure you create and manage all directories and files by hand. You may use `/data/<username>/<projectname>/` for data synced to the storage server and `/home/<username>/<projectname>/` for local data. If you use the local home directory make sure to create and manage `ttl.txt` by hand or an appropriate script. Data outside these directories is conbsidered a mistake and can be removed at any time.

Since you can't have root privileges in the host system you will not be able to install software by yourself. If you need anything not yet installed you have to ask Pina to install it. She will ask for the purpose and since she needs to consider the security implications of each additional packet she might refuse to install the software. This is only the case for system wide software. You may install software in userspace (for example python envronments).