# syntax=docker/dockerfile:1

# --- Builder stage -----------------------------------------------------------
# Resolves and installs dependencies into a virtualenv using uv, from the single
# pyproject.toml / uv.lock. Build-time system libs for python-ldap live here.
FROM python:3.13-slim-trixie AS builder

# Pinned uv binary (pin a digest/tag you trust rather than :latest in prod).
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

# WORKDIR matches the final stage so the venv's absolute paths stay valid when
# it is copied across.
WORKDIR /backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsasl2-dev \
    libldap2-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install only the locked dependencies (not the project itself: package=false),
# in a cache-friendly layer that only busts when the lock/manifest change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


# --- Final stage -------------------------------------------------------------
FROM python:3.13-slim-trixie

ARG USER_ID=3000
ARG GROUP_ID=3000

RUN groupadd --gid ${GROUP_ID} pina && \
    groupadd --gid 999 docker && \
    useradd --uid ${USER_ID} --gid ${GROUP_ID} --shell /bin/bash --create-home pina && \
    usermod -a -G docker pina

RUN mkdir -p /home/pina/.ssh && chown -R pina:pina /home/pina/.ssh && chmod 700 /home/pina/.ssh
RUN mkdir -p /tmp/ansible_runner_dockerapp && chown -R pina:pina /tmp/ansible_runner_dockerapp

WORKDIR /backend

# Runtime OpenLDAP library, whose package name is Debian-release-specific:
#   - Debian 13 (trixie, used here): libldap2      (OpenLDAP 2.6)
#   - Debian 12 (bookworm):          libldap-2.5-0 (OpenLDAP 2.5)
# Keep this in step with the base image above, and with libldap2-dev in the
# builder stage (python-ldap links against the same OpenLDAP major at build time).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsasl2-2 \
    libldap2 \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Application code first, then the resolved venv on top (so a stray local .venv
# in the build context can't shadow the built one; also add .venv to
# .dockerignore).
COPY --chown=pina:docker . .
COPY --from=builder /backend/.venv /backend/.venv

# Put the venv on PATH so `gunicorn` / `python` resolve to it (no activation).
ENV PATH="/backend/.venv/bin:$PATH"

USER pina
EXPOSE 5000

# The actual command is set per-service in docker-compose, e.g.:
#   web:    gunicorn --worker-class gthread --workers 1 --threads 8 \
#                    --timeout 120 -b 0.0.0.0:5000 run:app
#   worker: python worker.py