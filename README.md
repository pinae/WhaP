# Fischer's Whale Pond (WhaP)

![Whap logo](whap/frontend/public/logo512.png)

*Fischer's Whale Pond* is a full-stack web application that provides a user-friendly graphical interface 
for creating and managing project-specific [Docker](https://www.docker.com/) containers on remote compute servers.

This project is designed for data scientists and students who need to quickly deploy development 
environments, particularly for tasks requiring GPU access. It abstracts away the underlying command-line tools 
and server configurations, allowing users to select pre-configured environments and resources through 
a clean web UI.

The goal is achieved by combining a modern web frontend with a powerful backend. 
When a user requests a container, the backend dynamically generates and executes an 
[Ansible](https://docs.ansible.com/) playbook to provision the environment on a target 
server precisely as specified. 
Real-time logs from the deployment process are streamed directly to the user's browser via WebSockets.

-----

## Ways to run WhalePond

There are three setups, meant for different things:

| Setup | What it is | How it runs |
| --- | --- | --- |
| **Development** | One machine, dev servers with auto-reload, no compute node | Data stores in Docker, application processes on your host |
| **Test** | One storage server and one compute node | Ansible, with a small inventory |
| **Production** | Storage server hosting the app, several compute servers | Ansible, same roles, larger inventory |

The development setup is described below. For the other two see
[Deploy with Ansible](#Deploy with Ansible) — they use
the same Ansible roles and differ only in the inventory you write.

-----

## Development setup

The database, Redis and InfluxDB run in Docker at the same versions production
uses. The backend, the worker and the frontend run directly on your host, so
you get native file watching, a debugger you can attach without ceremony, and
no container-user file ownership problems in your working tree. Dependency
versions still match production exactly, because `uv` and `yarn` resolve the
same `uv.lock` and `yarn.lock` the production images are built from.

This is not a deployment: cookies go over plain HTTP, the Werkzeug debugger is
enabled, and the credentials below are throwaway values in a public
repository.

### 1. Requirements

  * [Docker](https://docs.docker.com/engine/install/) with the `compose` plug-in
  * [uv](https://docs.astral.sh/uv/) — it installs the right Python itself
  * [Node.js](https://nodejs.org/) 20 with `yarn`

`python-ldap` is compiled from source, so on Debian or Ubuntu you also need:

```bash
sudo apt install build-essential libldap2-dev libsasl2-dev
```

### 2. Start the data stores

```bash
git clone https://github.com/pinae/WhaP.git
cd WhaP
docker compose up -d
```

This gives you PostgreSQL on `localhost:5432`, Redis on `localhost:6379` and
InfluxDB on `localhost:8086`, all bound to the loopback interface. Stop them
with `docker compose down`, or `docker compose down -v` to wipe the data.

### 3. Configure and migrate the backend

```bash
cd whap/backend
cp env.example .env
uv sync
uv run flask db upgrade
```

`env.example` is already filled in for this setup; read through it before
changing anything, the comments explain which values matter and why.

### 4. Create an admin user

The database starts empty and there is no LDAP server locally, so make
yourself a local account:

```bash
uv run flask create-admin
```

### 5. Run it — four terminals

```bash
# 1: Databases
docker compose up

# 1: API and WebSocket server, reloads on save
cd whap/backend && uv run python run.py

# 2: job runner, restart manually after changing worker code
cd whap/backend && uv run python worker.py

# 3: frontend dev server, hot reloads on save
cd whap/frontend && yarn install && yarn start
```

Then open http://localhost:3000. The frontend talks to the backend at
`http://localhost:5000`, configured in `whap/frontend/.env`.

The worker deliberately does not reload — restarting it mid-job would orphan a
running playbook.

### Running the backend tests

```bash
cd whap/backend
uv run python -m pytest -q
```

### Limits of the development setup

There is no compute server, so container provisioning cannot finish. You can
create projects and containers in the UI and watch a job start: the queue, the
WebSocket log stream and the error handling all get exercised, but the Ansible
run fails when it tries to reach a host. Anything touching real provisioning
belongs in the test setup.

LDAP is absent for the same reason. `LDAP_SERVER_URI` and `LDAP_USER_BASE_DN`
carry example values because the configuration check refuses to boot without
them; LDAP logins fail, local users work.

### Overriding the compose defaults

Values in `docker-compose.yml` can be overridden from a `.env` file next to it
in the repository root (gitignored). If you change the database credentials
there, change `DATABASE_URL` in `whap/backend/.env` to match.

## Basic Docker Deployment Setup

You may deploy this as a multi-container application using Docker Compose. However 
note that there is a Ansible based setup that gives you the same with less manual configuration.

The following instructions assume you have [Docker](https://docs.docker.com/engine/install/) and its `compose` plug-in 
installed on your host machine.

### 1\. Configuration

Before launching the application, you must create several configuration files and directories 
at the root of the project.

**a. Environment Files** Create two environment files: `.env.prod` for the application 
and `.env.db` for the database.

**`.env.prod` (Application Configuration):**

```env
# Generate a new, strong secret key for production
SECRET_KEY=generate_a_real_secret_key_here

# Database connection string
DATABASE_URL=postgresql://whap_user:a_secure_password@db:5432/whap_db

# Paths inside the container for Ansible volumes
ANSIBLE_RUNNER_DIR=/app/ansible_runner
ANSIBLE_PROJECT_DIR=/app/ansible_project
ANSIBLE_ROLES_PATH=/app/ansible_project/roles
ANSIBLE_CONTAINER_BASE_DIR=/docker
PROJECT_HOST_BASE_PATH=/data/projects
ANSIBLE_SSH_PRIVATE_KEY_FILE=/root/.ssh/id_rsa_compute

# Internal URL for worker-to-backend communication
INTERNAL_API_URL=http://backend:5000/api/internal/job_update

# LDAP Settings (must be configured)
LDAP_SERVER_URI="ldaps://ldap.example.com:636"
LDAP_USER_BASE_DN="ou=people,dc=example,dc=com"
LDAP_BIND_USER="cn=service_account,ou=services,dc=example,dc=com"
LDAP_BIND_PASSWORD="service_account_password"
LDAP_TLS_OPTION="DEMAND"
```

**`.env.db` (Database Credentials):**

```env
POSTGRES_USER=whap_user
POSTGRES_PASSWORD=a_secure_password
POSTGRES_DB=whap_db
```

**b. Host Volume Directories** The application requires access to your Ansible roles and an SSH key 
to connect to compute servers. Create these directories at the project root:

```bash
# Create a directory for your Ansible project (roles, host_vars, etc.)
mkdir -p ./ansible_project/roles

# Create a directory for the SSH key
mkdir -p ./ansible_ssh_key
```

  * Place your Ansible roles into the `./ansible_project/roles` directory.
  * Place the SSH private key used to access your compute servers into `./ansible_ssh_key/id_rsa`.

### 2\. Build and Launch Containers

Once configured, use Docker Compose to build the images and launch the application stack.

```bash
# Build images and start all services in detached mode
docker compose -f docker-compose.yml up -d --build
```

### 3\. Initialize the Database

After the containers are running, you must initialize the database schema by applying the migrations.

```bash
# Wait a moment for the database to be fully ready
sleep 15

# 1. Apply database schema migrations
docker compose -f docker-compose.yml exec backend flask db upgrade
```

### 4\. Create an Admin User

Finally, create the initial administrator account.

```bash
# Run the interactive command to create your admin user
docker compose -f docker-compose.yml exec backend flask create-admin
```

Your application is now deployed and ready to be accessed.

## Deploy with Ansible

WhalePond needs two things: this repository (the application and its generic
Ansible roles), and a place to keep your own inventory — hostnames, passwords,
LDAP credentials — which must never live in a public repository.

The recommended layout keeps them separate. You create a private repository (or
just a private directory) for your configuration and include WhaP inside it:

    my-whap/                  # private: your inventory and secrets
    ├── ansible.cfg
    ├── inventory/            # your real hosts, host_vars, group_vars
    ├── plays/                # your playbooks
    ├── roles/                # your own site-specific roles (may be empty)
    └── WhaP/                 # this repository, as a submodule

### 1. Create the private repository

    mkdir my-whap && cd my-whap
    git init
    mkdir -p inventory/host_vars inventory/group_vars plays roles

### 2. Add WhaP

As a submodule, if `my-whap` is a git repository:

    git submodule add https://github.com/pinae/WhaP.git WhaP

Or as a plain clone, if you would rather not use submodules:

    git clone https://github.com/pinae/WhaP.git WhaP
    echo "WhaP/" >> .gitignore

The directory must be named `WhaP`. If you rename it, set `app_subdir` in your
host_vars to match.

### 3. Ansible install and set-up

First install `sshpass` for the first login without public key. On Ubuntu or Debian use:
```shell
sudo apt install sshpass build-essential libldap2-dev libsasl2-dev
```
The libraries `build-essential`, `libldap2-dev` and `libsasl2-dev` are needed to build python-ldap
during the setup of the `uv` environment in the next step.

Then [install Ansible](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html). 
We recommend using `uv` with the pyproject.toml in the whap/backend/ folder of the repository:
```shell
cd WhaP/whap/backend
uv sync
source WhaP/whap/backend/.venv/bin/activate
```

The following commands use `uv` to run the ansible commands from within a virtual environment. 
The source command activates this environment and after that `ansible-galaxy` and `ansible-playbook`
are inside your $PATH. You may also just install system packages for ansible like this:
`sudo apt install ansible-core`

### 4. Configure Ansible

Create `ansible.cfg` in `my-whap`:

    [defaults]
    inventory = inventory
    roles_path = roles:WhaP/roles
    host_key_checking = False

Your own roles are searched first, so you can override a WhaP role by giving a
role in `roles/` the same name.

### 5. Create your inventory

Copy the examples and edit them. Every placeholder value must be replaced:

    cp WhaP/inventory.example/hosts inventory/hosts
    cp WhaP/inventory.example/group_vars/all.yml inventory/group_vars/
    cp WhaP/inventory.example/host_vars/*.yml inventory/host_vars/

Rename the host_vars files to match your real hostnames. `storage01.example.com.yml`
configures the machine running the web application; `worker01.example.com.yml`
configures a compute server.

### 6. Install dependencies

    ansible-galaxy install -r WhaP/requirements.yml

### 7. Write a playbook and deploy

Copy `WhaP/plays.example/whap.yml` to `plays/whap.yml`, adjust the `hosts:` line
to match a group in your inventory, then:

    ansible-playbook plays/whap.yml

### Keeping WhaP up to date

    git -C WhaP pull origin main
    git add WhaP && git commit -m "Update WhaP"      # submodule only

If you clone `my-whap` on another machine, fetch the submodule too:

    git clone --recurse-submodules <your-repo-url>
    # or, in an existing checkout:
    git submodule update --init --recursive

### Docker registry (optional)

Roles from the 2510 generation pull their images from a registry instead of
building locally. Set `DOCKER_REGISTRY` in `.env.prod` (or `whap_registry` in your
host_vars) to point at it. Leave it empty to use the older build-based roles.

## Run the playbook

For the first server setup you need to allow login with `--ask-pass`:

```shell
ansible-playbook plays.example/initial-setup.yml -i hosts --ask-pass --ask-become-pass
```

```shell script
ansible-playbook plays.example/whap.yml -i hosts
```

-----

## Architecture for Developers

The application is split into two primary components: a backend API and 
a frontend single-page application (SPA), allowing for independent development.

### Backend

The backend is a [Python](https://www.python.org/) application built with the [Flask](https://flask.palletsprojects.com/en/stable/) web framework, 
following an application factory pattern (`create_app` in `backend/app/__init__.py`).

  * **Orchestration & Core Logic**: The primary function is to manage Docker container lifecycles on remote servers. This is uniquely handled not by a Docker SDK, but by the **`ansible-runner`** library. API endpoints dynamically generate Ansible playbooks based on user requests and execute them to provision and manage containers. This approach externalizes the deployment complexity into Ansible roles.
  * **Database**: All application state (users, projects, containers, etc.) is stored in a [PostgreSQL](https://www.postgresql.org/) database, managed via the **SQLAlchemy** ORM and **Flask-Migrate**.
  * **Authentication**: The app supports both an internal user database (`LocalUser` model) and authentication against an external **LDAP** server. A set of user wrapper classes (`LocalUserWrapper`, `LdapUserWrapper`) provides a consistent, abstract interface for handling either user type throughout the application.
  * **Asynchronous Jobs and Live Updates**: To provide real-time feedback for long-running Ansible jobs, the application uses a worker-based, asynchronous architecture backed by a Redis queue:
    1.  A user action (e.g., create container) generates an `AnsibleJob` record in the database with a `PENDING` status.
    2.  A separate `worker.py` process periodically polls the database for pending jobs (both `AnsibleJob` and `FileOperationJob`).
    3.  Upon finding a job, it marks the job `RUNNING` and launches a `run_job.py` subprocess, which executes the Ansible playbook via `ansible-runner`.
    4.  As the playbook runs, `ansible-runner` triggers a callback for each log event. The callback pushes the event onto a Redis list (`job_updates_queue`).
    5.  The web process (`run.py`) runs a background consumer that drains the queue in FIFO order, persists state changes, and emits each log line over a **Flask-SocketIO** WebSocket connection to the specific user's room.
    6.  When the job finishes, the final state is committed and an `ansible_job_completed` event is emitted over WebSocket to signal the frontend to refresh its state.

### Frontend

The frontend is a modern single-page application built with [React](https://react.dev/).

  * **UI & Design**: The user interface is built using the **Material-UI (MUI)** component library, creating a clean and responsive design.
  * **State Management**: Global state, particularly for user authentication, is managed through React's **Context API** (`AuthContext`). This context provides components with user information, authentication status, and login/logout functions. Local component state is handled via standard React hooks like `useState` and `useEffect`.
  * **Communication**: The frontend interacts with the backend through two channels:
      * **REST API**: For standard operations like fetching data and creating resources, it makes asynchronous requests to the backend's RESTful API using the **`axios`** library.
      * **WebSockets**: For receiving live updates during container provisioning, it establishes a WebSocket connection using the **`socket.io-client`** library. It joins a specific "room" for each container job to listen for log events (`ansible_log`) and the final completion signal (`ansible_job_completed`).

-----

## Running Tests

The backend test suite is written using `pytest`, and the Python virtual environment is managed by `uv`. 
Run the tests from the `whap/backend/` directory:

```bash
uv run pytest
```

This runs everything under `whap/backend/tests/` with verbose output (configured in `pyproject.toml`).

### Coverage

`pytest-cov` is included in the dev dependencies. For a coverage report of the `app` package:

```bash
# Terminal report, listing the line numbers each module is missing
uv run pytest --cov=app --cov-report=term-missing
```

For a browsable HTML report (written to `htmlcov/`; open `htmlcov/index.html`):

```bash
uv run pytest --cov=app --cov-report=html
```

The measured package, branch coverage, and omitted paths are configured in the `[tool.coverage.*]` 
sections of `pyproject.toml`.