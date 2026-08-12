# Development Setup Guide

This guide explains how to set up the project for local development.

## Prerequisites

* **Git:** For cloning the repository.
* **Python:** Version 3.10 or higher.
* **Pipenv:** For managing Python dependencies and virtual environments (`pip install pipenv`).
* **Docker & Docker Compose:** For running the development database ([Install Docker](https://docs.docker.com/get-docker/)). Ensure the Docker daemon is running.
* **Node.js & Yarn/npm:** For managing frontend dependencies and running the frontend development server ([Install Node.js](https://nodejs.org/)).

## 1. Clone the Repository

```bash
git clone <your-repository-url>
cd whap # Or your project's root directory name
```

Install dependencies for python-ldap:

```shell
sudo apt install libsasl2-dev python-dev-is-python3 libldap2-dev libssl-dev
```

Install the pipenv:

```shell
pipenv install -r requirements.txt
```

## 2. Backend Setup
### a. Configure Environment

Navigate to the backend directory:
```bash
cd backend
```

Create a `.env` file by copying the example (if one exists) or creating it manually. This file stores sensitive configuration and is ignored by Git.
```bash
# Example: copy if template exists
cp .env.example .env

# Or create manually: 
touch .env
```

Edit the `backend/.env` file with your specific settings. Pay close attention to:

`SECRET_KEY`: Generate a strong, random secret key (e.g., using `python -c 'import secrets; print(secrets.token_hex(32))'`).
`DATABASE_URL`: This must match the database credentials you will use in `docker-compose.yml`. For the default Docker setup, it should point to localhost or 127.0.0.1 on port 5432.

```
# backend/.env example line
DATABASE_URL='postgresql://mlcontainerwebinterface:4Hj#Dg7kp9S2%fgPmcDa@localhost:5432/mlcontainerwebinterface_db'

LDAP_* variables: Configure these if you intend to test LDAP authentication.
ANSIBLE_ROLES_PATH: Set the absolute path to your Ansible roles directory.
CORS_ORIGINS: Keep as http://localhost:3000 for development.
```

### b. Install Dependencies

Install the required Python packages using Pipenv:

```bash
# Make sure you are in the 'backend' directory
pipenv install --dev
```

(This installs packages from Pipfile and creates/uses a virtual environment).

## 3. Database Setup (PostgreSQL via Docker)

Navigate to the project's root directory (where docker-compose.yml is located).

```bash
# If you are in backend/, go up one level:
cd ..
```

Ensure the credentials (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB) in docker-compose.yml exactly match those used in your backend/.env file's DATABASE_URL.
Start the PostgreSQL database container in the background:

```bash
docker-compose up -d
```

The first time you run this, it will download the Postgres image.
This creates the database instance but not the application tables yet.

## 4. Database Migrations (Apply Schema)

This step creates the necessary tables (like local_user, project, container_instance, etc.) in the database based on your Flask models.

Navigate back to the backend directory:
```bash
cd backend
```

Apply the migrations. This must be done after the database container is running.
```bash
pipenv run flask db upgrade
```

You should see output indicating that migrations are being applied. If this is the very first time, it will create all tables.

(Note: You only need pipenv run flask db migrate -m "description" when you change your SQLAlchemy models in backend/app/models.py to generate a new migration script. upgrade applies existing scripts.)

## 5. Create Initial Admin User

Create the local administrator account you can use to log in and test the admin interface.

Make sure you are still in the backend directory.
Run the custom Flask CLI command:
```bash
pipenv run flask create-admin
```
Follow the prompts to set the username (default is admin) and password for the local admin user.

## 6. Run Backend Development Server

Make sure you are still in the backend directory.
Start the Flask development server:
```bash
pipenv run flask run
```

The backend API should now be running, typically on http://localhost:5000.

## 7. Frontend Setup

Open a new terminal window/tab.
Navigate to the frontend directory:
```bash
cd ../frontend # Or the correct path from your current location
```
Install Node.js dependencies:
```bash
# Using Yarn (recommended if yarn.lock exists)
yarn install

# OR using npm (if package-lock.json exists)
# npm install
```

Start the frontend development server:
```bash
# Using Yarn
yarn start

# OR using npm
# npm start
```

This will typically open the application in your web browser at http://localhost:3000.

## 8. Access the Application

Open your web browser and navigate to http://localhost:3000.
You should see the login screen. You can now log in using the local admin credentials you created.

## Stopping the Development Environment

* Frontend Server: Press Ctrl+C in the terminal where yarn start or npm start is running.
* Backend Server: Press Ctrl+C in the terminal where pipenv run flask run is running.
* Database Container: Navigate to the directory containing docker-compose.yml (project root) and run:
```bash
docker-compose down
```

(This stops and removes the container. Your data is safe in the postgres_data volume).