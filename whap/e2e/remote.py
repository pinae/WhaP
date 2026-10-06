"""Logging into a container over SSH, as its user would."""
import socket
import time
from dataclasses import dataclass

import paramiko


@dataclass
class Result:
    exit_status: int
    stdout: str
    stderr: str

    def __str__(self):
        return f"exit {self.exit_status}\n--- stdout ---\n{self.stdout}\n--- stderr ---\n{self.stderr}"


class ContainerShell:
    """An SSH session into a container, authenticated by key or by password.

    Containers are created fresh for every test, so there is no host key worth
    pinning; unknown keys are accepted. Connecting is retried for a while:
    sshd in a container that has just been reported RUNNING may still be
    starting.
    """

    def __init__(self, host, username, *, key_path=None, password=None, port=22, connect_within=60):
        if (key_path is None) == (password is None):
            raise ValueError("Authenticate with exactly one of key_path or password.")
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        credentials = ({"key_filename": str(key_path)} if key_path
                       else {"password": password})
        deadline = time.monotonic() + connect_within
        while True:
            try:
                # Only the credential given: no agent, no ~/.ssh keys, so a key
                # test cannot pass on some other key and a password test cannot
                # pass on a key.
                self.client.connect(host, port=port, username=username, timeout=10, banner_timeout=20,
                                    auth_timeout=20, allow_agent=False, look_for_keys=False, **credentials)
                return
            except paramiko.AuthenticationException:
                raise  # a wrong credential won't fix itself
            except (OSError, socket.timeout, paramiko.SSHException) as e:
                if time.monotonic() > deadline:
                    raise ConnectionError(f"Could not reach {username}@{host}:{port} within "
                                          f"{connect_within}s: {e}") from e
                time.sleep(2)

    def run(self, command, timeout=120):
        """Run a command through a login shell, so the user's profile is in effect."""
        _, stdout, stderr = self.client.exec_command(f"bash -lc {_quote(command)}", timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        return Result(exit_status, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace"))

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _quote(command):
    return "'" + command.replace("'", "'\"'\"'") + "'"
