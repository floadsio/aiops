"""SSH key encryption, decryption, and agent management service.

This service handles:
- Encrypting/decrypting SSH private keys for database storage
- Injecting keys into ssh-agent temporarily for git operations
- Cleaning up ssh-agent sessions after use
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from flask import current_app


class SSHKeyServiceError(Exception):
    """Base exception for SSH key service errors."""


def _get_encryption_key() -> bytes:
    """Get the encryption key from Flask config.

    The key should be set in .env as SSH_KEY_ENCRYPTION_KEY.
    If not set, generates a new one (should only happen in development).
    """
    key_str = current_app.config.get("SSH_KEY_ENCRYPTION_KEY")

    if not key_str:
        # In production, this should be set in .env
        # Generate a key for development/testing
        key = Fernet.generate_key()
        current_app.logger.warning(
            "SSH_KEY_ENCRYPTION_KEY not set, using generated key. "
            "Set SSH_KEY_ENCRYPTION_KEY in .env for production!"
        )
        return key

    return key_str.encode("utf-8")


def encrypt_private_key(private_key: str) -> bytes:
    """Encrypt an SSH private key for database storage.

    Args:
        private_key: The private key content as string

    Returns:
        Encrypted key as bytes

    Raises:
        SSHKeyServiceError: If encryption fails
    """
    try:
        key = _get_encryption_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(private_key.encode("utf-8"))
        return encrypted
    except Exception as exc:
        raise SSHKeyServiceError(f"Failed to encrypt private key: {exc}") from exc


def decrypt_private_key(encrypted_key: bytes) -> str:
    """Decrypt an SSH private key from database storage.

    Args:
        encrypted_key: The encrypted key bytes from database

    Returns:
        Decrypted private key as string

    Raises:
        SSHKeyServiceError: If decryption fails
    """
    try:
        key = _get_encryption_key()
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted_key)
        return decrypted.decode("utf-8")
    except Exception as exc:
        raise SSHKeyServiceError(f"Failed to decrypt private key: {exc}") from exc


def _start_ssh_agent() -> tuple[str, int]:
    """Start a new ssh-agent process.

    Returns:
        Tuple of (auth_sock_path, agent_pid)

    Raises:
        SSHKeyServiceError: If agent fails to start
    """
    try:
        # Start ssh-agent and capture output
        result = subprocess.run(
            ["ssh-agent", "-s"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )

        # Parse output to get SSH_AUTH_SOCK and SSH_AGENT_PID
        auth_sock = None
        agent_pid = None

        for line in result.stdout.splitlines():
            if "SSH_AUTH_SOCK=" in line:
                auth_sock = line.split("SSH_AUTH_SOCK=")[1].split(";")[0]
            elif "SSH_AGENT_PID=" in line:
                agent_pid = int(line.split("SSH_AGENT_PID=")[1].split(";")[0])

        if not auth_sock or not agent_pid:
            raise SSHKeyServiceError("Failed to parse ssh-agent output")

        return auth_sock, agent_pid
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise SSHKeyServiceError(f"Failed to start ssh-agent: {exc}") from exc


def _add_key_to_agent(auth_sock: str, private_key_content: str) -> None:
    """Add a private key to ssh-agent.

    Args:
        auth_sock: SSH_AUTH_SOCK path
        private_key_content: The private key content

    Raises:
        SSHKeyServiceError: If key addition fails
    """
    # Write key to temporary file (ssh-add requires a file)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
        f.write(private_key_content)
        key_path = f.name

    try:
        # Set restrictive permissions
        os.chmod(key_path, 0o600)

        # Add key to agent
        env = os.environ.copy()
        env["SSH_AUTH_SOCK"] = auth_sock

        subprocess.run(
            ["ssh-add", key_path],
            env=env,
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise SSHKeyServiceError(f"Failed to add key to ssh-agent: {exc}") from exc
    finally:
        # Clean up temporary key file
        try:
            os.unlink(key_path)
        except OSError:
            pass


def _kill_ssh_agent(agent_pid: int) -> None:
    """Kill an ssh-agent process.

    Args:
        agent_pid: The agent process ID

    Raises:
        SSHKeyServiceError: If agent termination fails
    """
    try:
        subprocess.run(
            ["kill", str(agent_pid)],
            capture_output=True,
            timeout=5,
            check=True,
        )
    except subprocess.SubprocessError as exc:
        raise SSHKeyServiceError(f"Failed to kill ssh-agent: {exc}") from exc


@contextmanager
def ssh_key_context(encrypted_private_key: bytes):
    """Context manager for temporarily injecting an SSH key into ssh-agent.

    This starts an ssh-agent, adds the key, yields the auth sock path,
    and cleans up afterward.

    Args:
        encrypted_private_key: The encrypted private key from database

    Yields:
        SSH_AUTH_SOCK path to use for git operations

    Raises:
        SSHKeyServiceError: If any step fails

    Example:
        with ssh_key_context(ssh_key.encrypted_private_key) as auth_sock:
            env = os.environ.copy()
            env['SSH_AUTH_SOCK'] = auth_sock
            subprocess.run(['git', 'pull'], env=env)
    """
    auth_sock = None
    agent_pid = None

    try:
        # Decrypt the private key
        private_key = decrypt_private_key(encrypted_private_key)

        # Start ssh-agent
        auth_sock, agent_pid = _start_ssh_agent()

        # Add key to agent
        _add_key_to_agent(auth_sock, private_key)

        # Yield the auth sock for use
        yield auth_sock

    finally:
        # Clean up agent
        if agent_pid:
            try:
                _kill_ssh_agent(agent_pid)
            except SSHKeyServiceError:
                # Best effort cleanup
                current_app.logger.warning(f"Failed to kill ssh-agent {agent_pid}")


def migrate_key_to_database(ssh_key_model, private_key_path: str) -> None:
    """Migrate an SSH key from filesystem to database storage.

    Reads the private key from the filesystem, encrypts it, and stores it
    in the database. Does not delete the original file.

    Args:
        ssh_key_model: The SSHKey model instance
        private_key_path: Path to the private key file

    Raises:
        SSHKeyServiceError: If migration fails
    """
    try:
        # Read private key from file
        key_path = Path(private_key_path)
        if not key_path.exists():
            raise SSHKeyServiceError(f"Private key file not found: {private_key_path}")

        with open(key_path, "r") as f:
            private_key_content = f.read()

        # Encrypt and store in database
        encrypted_key = encrypt_private_key(private_key_content)
        ssh_key_model.encrypted_private_key = encrypted_key

        current_app.logger.info(
            f"Migrated SSH key '{ssh_key_model.name}' to database storage"
        )

    except (OSError, IOError) as exc:
        raise SSHKeyServiceError(f"Failed to read private key file: {exc}") from exc
