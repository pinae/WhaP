import os
import shutil
from pathlib import Path
from flask import current_app
from ..user_management import LdapUserWrapper, LocalUserWrapper
from ..services import ldap_service


def _get_user_ids(user):
    """
    Helper function to get UID and GID from a user wrapper object.
    For LDAP users, it fetches fresh details to ensure accuracy.
    For local users, it uses the default container UID/GID from config.

    Args:
        user (User): A LocalUserWrapper or LdapUserWrapper instance.

    Returns:
        tuple: (uid, gid) as integers, or (None, None) if details cannot be found.
    """
    app = current_app._get_current_object()
    with app.app_context():
        if isinstance(user, LdapUserWrapper):
            # Re-fetch details to ensure they are current
            ldap_details = ldap_service.get_ldap_user_details(user.username)
            if ldap_details and ldap_details.get('uidNumber') and ldap_details.get('gidNumber'):
                return int(ldap_details['uidNumber']), int(ldap_details['gidNumber'])
            else:
                app.logger.error(f"Could not retrieve UID/GID for LDAP user {user.username}.")
                return None, None
        elif isinstance(user, LocalUserWrapper):
            # Local users run under a generic UID/GID inside the container as they don't have one on the host
            default_uid = current_app.config.get('DEFAULT_CONTAINER_UID', 1000)
            default_gid = current_app.config.get('DEFAULT_CONTAINER_GID', 1000)
            return int(default_uid), int(default_gid)
        else:
            app.logger.error(f"Unknown user type provided to _get_user_ids: {type(user)}")
            return None, None


def create_directory(path: Path, user):
    """
    Idempotently creates a directory and sets its ownership.

    Args:
        path (Path): The directory path to create.
        user (User): The user object (LocalUserWrapper or LdapUserWrapper) to own the directory.
    """
    app = current_app._get_current_object()
    with app.app_context():
        uid, gid = _get_user_ids(user)
        if uid is None or gid is None:
            app.logger.error(f"Aborting directory creation for '{path}' due to missing user IDs.")
            return

        if path.is_dir():
            app.logger.debug(f"Directory '{path}' already exists.")
            # Ensure ownership is correct even if it exists
            if path.stat().st_uid != uid or path.stat().st_gid != gid:
                try:
                    os.chown(path, uid, gid)
                    app.logger.info(f"Corrected ownership for existing directory '{path}' to UID={uid}, GID={gid}.")
                except OSError as e:
                    app.logger.error(f"Failed to change ownership of existing directory '{path}': {e}")
        else:
            try:
                os.makedirs(path, exist_ok=True)
                os.chown(path, uid, gid)
                app.logger.info(f"Created directory '{path}' and set ownership to UID={uid}, GID={gid}.")
            except OSError as e:
                app.logger.error(f"Error creating directory '{path}' or setting its ownership: {e}")


def rename_directory(old_path: Path, new_path: Path, user):
    """
    Idempotently renames a directory and ensures correct ownership of the new directory.

    Args:
        old_path (Path): The original directory path.
        new_path (Path): The target directory path.
        user (User): The user object to own the new directory.
    """
    app = current_app._get_current_object()
    with app.app_context():
        uid, gid = _get_user_ids(user)
        if uid is None or gid is None:
            app.logger.error(f"Aborting directory rename for '{old_path}' due to missing user IDs.")
            return

        # If new_path already exists and is the correct destination, we're done.
        if new_path.is_dir():
            app.logger.debug(f"Target directory '{new_path}' already exists. Rename operation is considered complete.")
            # Ensure ownership is correct
            if new_path.stat().st_uid != uid or new_path.stat().st_gid != gid:
                 try:
                    os.chown(new_path, uid, gid)
                    app.logger.info(f"Corrected ownership for existing target directory '{new_path}'.")
                 except OSError as e:
                    app.logger.error(f"Failed to change ownership of existing target directory '{new_path}': {e}")
            return

        # If old_path doesn't exist, there's nothing to rename.
        if not old_path.is_dir():
            app.logger.warning(f"Source directory '{old_path}' does not exist for renaming. Assuming already renamed.")
            return

        try:
            os.rename(old_path, new_path)
            os.chown(new_path, uid, gid)
            app.logger.info(f"Renamed directory '{old_path}' to '{new_path}' and set ownership.")
        except OSError as e:
            app.logger.error(f"Error renaming directory from '{old_path}' to '{new_path}': {e}")


def delete_directory(path: Path):
    """
    Idempotently deletes a directory.

    Args:
        path (Path): The directory path to delete.
    """
    app = current_app._get_current_object()
    with app.app_context():
        if not path.exists():
            app.logger.debug(f"Directory '{path}' does not exist. Deletion is considered complete.")
            return

        if not path.is_dir():
            app.logger.error(f"Path '{path}' is not a directory. Cannot delete.")
            return

        try:
            shutil.rmtree(path)
            app.logger.info(f"Successfully deleted directory '{path}'.")
        except OSError as e:
            app.logger.error(f"Error deleting directory '{path}': {e}")


def ensure_lines_in_file(file_path: Path, lines: list, user):
    """
    Idempotently ensures a file exists and contains specific lines.
    Creates parent directories if they don't exist.

    Args:
        file_path (Path): The full path to the file.
        lines (list): A list of strings that should be in the file.
        user (User): The user object to own the file.
    """
    app = current_app._get_current_object()
    with app.app_context():
        uid, gid = _get_user_ids(user)
        if uid is None or gid is None:
            app.logger.error(f"Aborting file operation for '{file_path}' due to missing user IDs.")
            return

        # Ensure parent directory exists and has correct ownership
        parent_dir = file_path.parent
        create_directory(parent_dir, user)

        existing_lines = set()
        if file_path.is_file():
            try:
                with open(file_path, 'r') as f:
                    existing_lines = set(line.strip() for line in f)
            except IOError as e:
                app.logger.error(f"Could not read existing file '{file_path}': {e}")
                return # Abort if we can't read the file

        lines_to_add = [line for line in lines if line.strip() not in existing_lines]

        if not lines_to_add:
            app.logger.debug(f"All specified lines already exist in '{file_path}'.")
            # Still, ensure ownership is correct on the existing file
            if file_path.exists() and (file_path.stat().st_uid != uid or file_path.stat().st_gid != gid):
                try:
                    os.chown(file_path, uid, gid)
                    app.logger.info(f"Corrected ownership for existing file '{file_path}'.")
                except OSError as e:
                    app.logger.error(f"Failed to change ownership of existing file '{file_path}': {e}")
            return

        try:
            with open(file_path, 'a') as f:
                for line in lines_to_add:
                    f.write(line + '\n')
            app.logger.info(f"Added {len(lines_to_add)} line(s) to '{file_path}'.")

            # Set ownership after creating/modifying
            os.chown(file_path, uid, gid)
        except IOError as e:
            app.logger.error(f"Error writing to file '{file_path}': {e}")


def get_gids_for_paths(paths: list):
    """
    Inspects a list of directory paths and returns a unique list of their group IDs (GIDs).

    Args:
        paths (list): A list of strings or Path objects representing directories.

    Returns:
        list: A list of unique integer GIDs found for the existing directories.
    """
    app = current_app._get_current_object()
    unique_gids = set()
    with app.app_context():
        for path_str in paths:
            path = Path(path_str)
            if path.is_dir():
                try:
                    gid = path.stat().st_gid
                    unique_gids.add(gid)
                    app.logger.debug(f"Found GID {gid} for path '{path}'.")
                except OSError as e:
                    app.logger.error(f"Could not stat directory '{path}': {e}")
            else:
                app.logger.warning(f"Path '{path}' is not an existing directory. Skipping GID lookup.")
    return list(unique_gids)
