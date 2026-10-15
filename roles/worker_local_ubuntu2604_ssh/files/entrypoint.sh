#!/bin/bash
set -e

# Default values if variables are not set
USERNAME=${USERNAME:-user}
USER_ID=${USER_ID:-1000}
GROUP_ID=${GROUP_ID:-1000}
# Check if we are using Docker Secrets (File) or Fallback Env Var
if [ -n "$PASSWORD_FILE" ] && [ -f "$PASSWORD_FILE" ]; then
    PASSWORD=$(cat "$PASSWORD_FILE")
elif [ -z "$PASSWORD" ]; then
    echo "Error: No password provided via SECRET or ENV."
    exit 1
fi

echo "Starting container setup for user: $USERNAME ($USER_ID:$GROUP_ID)..."

# 1. Handle Group
# Check if group ID exists
if getent group "${GROUP_ID}" > /dev/null; then
    EXISTING_GROUP=$(getent group "${GROUP_ID}" | cut -d: -f1)
    if [ "${EXISTING_GROUP}" != "${USERNAME}" ]; then
        echo "Group ID ${GROUP_ID} exists as ${EXISTING_GROUP}. Renaming to ${USERNAME}..."
        groupmod -n "${USERNAME}" "${EXISTING_GROUP}"
    fi
else
    echo "Creating group ${USERNAME} with GID ${GROUP_ID}..."
    groupadd --gid "${GROUP_ID}" "${USERNAME}"
fi

# 2. Handle User
if getent passwd "${USER_ID}" > /dev/null; then
    EXISTING_USER=$(getent passwd "${USER_ID}" | cut -d: -f1)
    if [ "${EXISTING_USER}" != "${USERNAME}" ]; then
        echo "User ID ${USER_ID} exists as ${EXISTING_USER}. Modifying..."

        # Check if target home directory already exists (e.g. Volume Mount)
        if [ -d "/home/${USERNAME}" ]; then
            echo "Home directory /home/${USERNAME} exists (Volume). Updating info without moving files."
            # -d updates the home path in /etc/passwd, but NO -m (move)
            usermod -l "${USERNAME}" -d "/home/${USERNAME}" "${EXISTING_USER}"
        else
            echo "Moving home directory..."
            usermod -l "${USERNAME}" -d "/home/${USERNAME}" -m "${EXISTING_USER}"
        fi
    fi
else
    echo "Creating user ${USERNAME} with UID ${USER_ID}..."
    useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --shell /bin/bash --create-home "${USERNAME}"
fi

# 3. Setup Password
echo "${USERNAME}:${PASSWORD}" | chpasswd
echo "root:${PASSWORD}" | chpasswd

# 4. Sudo Setup
if ! getent group sudo > /dev/null; then
    echo "Group 'sudo' not found. Creating it..."
    groupadd sudo
fi
echo "${USERNAME} ALL=(root) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}"
chmod 0440 "/etc/sudoers.d/${USERNAME}"
usermod -a -G sudo ${USERNAME}

# 5. Handle Additional GIDs
if [ -n "${ADDITIONAL_GIDS}" ]; then
    echo "Processing additional GIDs: ${ADDITIONAL_GIDS}"
    # Replace commas with spaces
    for GID in $(echo "${ADDITIONAL_GIDS}" | tr ',' ' '); do
        # If group doesn't exist, create a dummy one
        if ! getent group "${GID}" > /dev/null; then
            groupadd --gid "${GID}" "shared_group_${GID}"
        fi
        # Add user to group
        usermod -aG "$(getent group "${GID}" | cut -d: -f1)" "${USERNAME}"
    done
fi

# 6. Ensure Home Directory Permissions
# (Crucial because volume mounts might mask ownership)
chown "${USER_ID}:${GROUP_ID}" "/home/${USERNAME}"

# 7. Generate SSH Host Keys if missing
# (Required because /etc/ssh might be ephemeral or we want fresh keys)
ssh-keygen -A

# 8. Start CMD
if [ "$1" = "/usr/sbin/sshd" ]; then
    echo "Setup complete. Executing command: $@"
    exec "$@"
else
    echo "Since $@ is not sshd. Dropping privileges to user ${USERNAME}..."
    # We use 'su' to run the command as the specific user preserving the environment variables.
    exec su - "${USERNAME}" -c "$*"
fi