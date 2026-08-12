# Getting started for a Thesis

Computational experiments tend to consume more compute than a laptop or PC at home is able to deliver (a gaming PC might suffice for some). To solve this we have four powerful compute servers which are used by the whole Machine Learning group. In order to not disturb the experiments run by others we use Docker containers which provide separated Enviroments for every user. The Containers can be configured and started in the Whale Pond.

To get access to the Whalpe Pond you have to write an email to [Pina.Merkert@ruhr-uni-bochum.de](mailto:Pina.Merkert@ruhr-uni-bochum.de). Pina will add you to the LDAP group of the group. LDAP is the directory system of the University and allows you to use your RUB-ID and password to log into the Whale Pond.

After Pina added you to the group you may have to manually trigger an update of the LDAP settings in the systems if IT.SERVICES. To trigger this you have to input your RUB-ID and password into [this form by IT.SERVICES: https://idm.ruhr-uni-bochum.de/rubiks/cip_rub.freischalten_start](https://idm.ruhr-uni-bochum.de/rubiks/cip_rub.freischalten_start).

The Whale Pond is availabe at this URL: [https://whap.storageserver.ig17s.rub.de](https://whap.storageserver.ig17s.rub.de)

> Tipp: SSH-Keys allows more secure authentication and can even be configured to not ask for a password at all. We recommend to use a SSH public key to authenticate at the containers you start. [This tutorial from GitHub is an excellent explanation on how to create a SSH key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent). Your SSH public key is usually located at `~/.ssh/id_ed25519.pub`. You can copy the public key with the commands stated in [this document](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account?platform=windows) for example with: `clip < ~/.ssh/id_ed25519.pub`. The Whale Pond has a tab for SSH keys. Click "Add SSH Key" there and paste the copied string in the field "Public Key String". You have to set a name like "Work laptop". After saving the key it is available for selection when you create an container and the Whale Pond will preinstall it in the container.

The Whale Pond expects you to structure your experiments into projects. A project corresponds	 to a folder on our storage server and for `local_`-Containers also a folder on the SSD of the compute server. This folder will be mounted inside the container at `/home/{your RUB-ID}/` and you will not be able to see any other folder from the container (except the shared folders and/or datasets you add during the container creation). The idea is that each project starts as a clean slate. If you want to access code from other projects you can share your own project with yourself and select it during the creation of the container for the new project.

If you use a `local_`-Container for fast SSD access to code and data you have to consider that your data lives only on the SSD of the compute server you selected. If you want to start a `local_`-Container for the same project on a different compute server they will have the same `~/synced/` directory but completely separate `~/`. You can ask Pina via mail or Element to copy your data from one server to the other. Or you can copy your data to `~/synced/` on one server and retrieve it from `~/synced/` on the other server (this uses NFS).

## Working with the containers

The IP addresses of your containers will only be accessible in the network of the RUB. You have to either use Eduroam or ethernet at the university or use the RUB-VPN. If you have connectivity problems try connecting via VPN. [Here is a general explanation for using the RUB-VPN](https://noc.rub.de/web/vpn_en) and [here is an axplanation on how to activate the personal IP address (PIP)](https://noc.rub.de/web/services/pip).

Try the connection with SSH on the console. The Whale Pond shows the SSH command you need to use in the box showing your running container (ready to copy to the clipboard). The command looks like this: `ssh {your RUB-ID}@{container-IP}`
You can add the port with `-t 22` but as we use the standard port 22 this can be omitted.

You can configure a SSH based remote connection in your IDE which makes working on a remote server much more convenient. [This explains the setup for VSCode](https://code.visualstudio.com/docs/remote/ssh#_getting-started).

You can see if the selected GPUs are available in the container with `nvidia-smi`. If you prefer real time data `nvtop` is more convenient (similar to `top` for the CPU utilization you close it with "q").

You have root-Access in your container so you can install system packages with `sudo`. For example: `sudo apt install nvtop`. You can also use `pip` to install python software system wide like this: `sudo pip install uv --break-system-packages`
However even in a rather minimal Linux environment like the containers there might be version issues if you overwrite python modules installed by the system with newer versions from PyPI. So we still recommend to use some kind of virtual envioronment. There are several options:

- The classic option is Virtualenv (`sudo apt install python3-virtualenv`). You can use `python3 -m venv env` to create a folder `env/` in the current folder which contains the python packages. You make python use those instead of the ones from system folders by activating the virtualenv with `source env/bin/activate` or `env\Scripts\activate.bat` on Windows. This is active in the current console window until you run `deactivate`. Dependencies are listed in `requirements.txt` and are installed with `pip install -r requirements.txt` (while the virtualenv is active).
- A more convenient option is `pipenv`. If you supply a `Pipfile` it contains the Dependencies which can be installed with `pipenv install` which creates the environment in a hidden folder and installs the dependencies in one go. You can still activate with `pipenv shell` but you can also run single commands using the environment with `pipenv run {command}`.
- Anaconda is very similar to pipenv but preinstalls a lot of additional packages. Instead of `pip` you use `conda` but the commands are very similar. Anaconda also manages your environments like pipenv and also offers a graphical interface which can not really be used on a remote machine.
- The new star is `uv`. It is very fast and can install more software than only python modules. There is no Ubuntu package for it yet but `sudo pip install uv --break-system-packages` works fine. It uses a config file called `pyproject.toml` which configures the dependencies and allows everything to be installed with `uv sync`. It usually stores packages in the hidden folder `.venv/` and you can activate the environment with `.venv/bin/activate` (very classical).

## Be fair!

Please be considerate of the needas of other users. The Whale Pond displays usage statistics and you can see which GPUs are still not completely full. Ask the group or your supersivor if it's OK to use all the GPUs. If in doubt leave one free and only run your processes on the other ones. You can simply select not all GPUs when starting the container. Or you can select which GPU to use in your Python code. If you block other users Pina might kill your processes or stop your container.

Since your Processes might get killed please make sure longer running processes use snapshots which save your work in regular intervals. This ensures that your progress does not get lost if Pina has to stop running processes.

Also make sure to not fill up the local SSD of the compute server. You always have your project directory on the storage server available at `~/synced/`. This is a great place to store snapshots, results and graphs you create and not loose them. Make sure your data is stored there and tidied up regularly.

The local prject folders contain a file `ttl.txt` with a date. After this date (or if the date is too far in the future or the file is missing) the local data might get deleted at any time. Make sure to set this to max. two weeks after the date you hand in your thesis.

Data on the storage server does not get automatically deleted. But if you are finished and you don't need the project files anymore let Pina know. She will tidy up on the storage server.