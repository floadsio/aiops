"""yadm (Yet Another Dotfiles Manager) service for managing user configuration files.

This service handles:
- Cloning and managing yadm dotfiles repositories
- GPG key management for encrypted files
- Bootstrap script execution
- File encryption/decryption
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from ..models import User

logger = logging.getLogger(__name__)


class YadmServiceError(Exception):
    """Base exception for yadm service errors."""

    pass


class YadmKeyEncryption:
    """Encryption utilities for storing GPG keys securely in the database."""

    @staticmethod
    def _get_encryption_key() -> bytes:
        """Get the encryption key from environment."""
        key_str = os.getenv("SSH_KEY_ENCRYPTION_KEY")
        if not key_str:
            raise YadmServiceError(
                "SSH_KEY_ENCRYPTION_KEY environment variable not set. "
                "Cannot encrypt/decrypt GPG keys."
            )
        return key_str.encode() if isinstance(key_str, str) else key_str

    @staticmethod
    def encrypt_gpg_key(private_key_data: bytes) -> bytes:
        """Encrypt GPG private key using Fernet symmetric encryption.

        Args:
            private_key_data: Raw GPG private key bytes

        Returns:
            Encrypted key bytes

        Raises:
            YadmServiceError: If encryption fails or key not configured
        """
        try:
            key = YadmKeyEncryption._get_encryption_key()
            cipher = Fernet(key)
            return cipher.encrypt(private_key_data)
        except (ValueError, TypeError) as exc:
            raise YadmServiceError(f"Failed to encrypt GPG key: {exc}") from exc

    @staticmethod
    def decrypt_gpg_key(encrypted_data: bytes) -> bytes:
        """Decrypt GPG private key from database.

        Args:
            encrypted_data: Encrypted key bytes from database

        Returns:
            Decrypted GPG private key bytes

        Raises:
            YadmServiceError: If decryption fails
        """
        try:
            key = YadmKeyEncryption._get_encryption_key()
            cipher = Fernet(key)
            return cipher.decrypt(encrypted_data)
        except InvalidToken as exc:
            raise YadmServiceError(f"Failed to decrypt GPG key: {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise YadmServiceError(f"Invalid encryption key or data: {exc}") from exc


def store_gpg_key_encrypted(
    user: User,
    private_key_data: bytes,
    key_id: str,
    passphrase: Optional[str] = None,
) -> None:
    """Store GPG private key encrypted in database.

    Args:
        user: User object to store key for
        private_key_data: Raw GPG private key bytes
        key_id: GPG key ID (e.g., "4F8B3C1A2D5E7F9A")
        passphrase: Optional passphrase for the key (encrypted separately if needed)

    Raises:
        YadmServiceError: If encryption or storage fails
    """
    try:
        encrypted_key = YadmKeyEncryption.encrypt_gpg_key(private_key_data)
        user.gpg_private_key_encrypted = encrypted_key
        user.gpg_key_id = key_id
        logger.info(f"Stored encrypted GPG key for user {user.email} (ID: {key_id})")
    except YadmServiceError as exc:
        logger.error(f"Failed to store GPG key for user {user.email}: {exc}")
        raise


def get_gpg_key_decrypted(user: User) -> Optional[bytes]:
    """Retrieve and decrypt GPG private key from database.

    Args:
        user: User object to retrieve key for

    Returns:
        Decrypted GPG private key bytes, or None if not configured

    Raises:
        YadmServiceError: If decryption fails
    """
    if not user.gpg_private_key_encrypted:
        return None

    try:
        return YadmKeyEncryption.decrypt_gpg_key(user.gpg_private_key_encrypted)
    except YadmServiceError as exc:
        logger.error(f"Failed to decrypt GPG key for user {user.email}: {exc}")
        raise


def import_gpg_key(
    linux_username: str,
    user_home: str,
    private_key_data: bytes,
    key_id: str,
    passphrase: Optional[str] = None,
) -> None:
    """Import GPG private key into user's keyring for yadm decryption.

    Args:
        linux_username: Linux username (for sudo execution)
        user_home: User's home directory
        private_key_data: Raw GPG private key bytes
        key_id: GPG key ID
        passphrase: Optional passphrase for the GPG key

    Raises:
        YadmServiceError: If import fails
    """
    try:
        # Create temporary file to store the key for import
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".gpg", delete=False
        ) as key_file:
            key_file.write(private_key_data)
            key_file.flush()
            key_path = key_file.name

        try:
            # Import key using gpg command
            cmd = ["gpg", "--import", key_path]
            if passphrase:
                cmd.extend(
                    [
                        "--pinentry-mode",
                        "loopback",
                        "--passphrase",
                        passphrase,
                    ]
                )

            # Run as target user via sudo
            sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
            result = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=user_home,
            )

            if result.returncode != 0:
                raise YadmServiceError(
                    f"Failed to import GPG key: {result.stderr or result.stdout}"
                )

            logger.info(
                f"Imported GPG key {key_id} for user {linux_username} "
                f"to {user_home}/.gnupg"
            )

        finally:
            # Clean up temporary key file
            Path(key_path).unlink(missing_ok=True)

    except subprocess.TimeoutExpired as exc:
        raise YadmServiceError(f"GPG import timed out: {exc}") from exc
    except Exception as exc:
        raise YadmServiceError(f"Failed to import GPG key: {exc}") from exc


def initialize_yadm_repo(
    linux_username: str,
    user_home: str,
    repo_url: str,
    branch: str = "main",
) -> None:
    """Clone yadm dotfiles repository to user's home directory.

    Args:
        linux_username: Linux username (for sudo execution)
        user_home: User's home directory
        repo_url: Git URL for the dotfiles repository
        branch: Git branch to checkout (default: main)

    Raises:
        YadmServiceError: If clone or initialization fails
    """
    try:
        # Initialize yadm repo
        cmd = [
            "yadm",
            "clone",
            "--bootstrap",
            "--no-prompt",
            "-b",
            branch,
            repo_url,
        ]

        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        result = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes for clone + bootstrap
            cwd=user_home,
        )

        if result.returncode != 0:
            raise YadmServiceError(
                f"Failed to initialize yadm repo: {result.stderr or result.stdout}"
            )

        logger.info(
            f"Initialized yadm repository for user {linux_username} "
            f"from {repo_url} (branch: {branch})"
        )

    except subprocess.TimeoutExpired as exc:
        raise YadmServiceError(f"yadm clone timed out: {exc}") from exc
    except Exception as exc:
        raise YadmServiceError(f"Failed to initialize yadm repo: {exc}") from exc


def apply_yadm_bootstrap(
    linux_username: str,
    user_home: str,
) -> None:
    """Run yadm bootstrap script to apply configurations.

    Args:
        linux_username: Linux username (for sudo execution)
        user_home: User's home directory

    Raises:
        YadmServiceError: If bootstrap execution fails
    """
    try:
        cmd = ["yadm", "bootstrap"]

        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        result = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=user_home,
        )

        if result.returncode != 0:
            logger.warning(
                f"yadm bootstrap completed with exit code {result.returncode}: "
                f"{result.stderr or result.stdout}"
            )
            # Don't raise error - bootstrap may have non-critical issues

        logger.info(f"Ran yadm bootstrap for user {linux_username}")

    except subprocess.TimeoutExpired as exc:
        raise YadmServiceError(f"yadm bootstrap timed out: {exc}") from exc
    except Exception as exc:
        raise YadmServiceError(f"Failed to apply yadm bootstrap: {exc}") from exc


def yadm_decrypt(
    linux_username: str,
    user_home: str,
) -> None:
    """Decrypt yadm-encrypted files after bootstrap.

    Args:
        linux_username: Linux username (for sudo execution)
        user_home: User's home directory

    Raises:
        YadmServiceError: If decryption fails
    """
    try:
        cmd = ["yadm", "decrypt"]

        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        result = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=user_home,
        )

        if result.returncode != 0:
            logger.warning(
                f"yadm decrypt completed with exit code {result.returncode}: "
                f"{result.stderr or result.stdout}"
            )
            # Don't raise error - may not have encrypted files

        logger.info(f"Decrypted yadm files for user {linux_username}")

    except subprocess.TimeoutExpired as exc:
        raise YadmServiceError(f"yadm decrypt timed out: {exc}") from exc
    except Exception as exc:
        raise YadmServiceError(f"Failed to decrypt yadm files: {exc}") from exc


def verify_yadm_setup(
    linux_username: str,
    user_home: str,
) -> bool:
    """Verify that yadm is properly set up for a user.

    Args:
        linux_username: Linux username
        user_home: User's home directory

    Returns:
        True if yadm is properly configured, False otherwise
    """
    try:
        # Check if .yadm directory exists
        yadm_dir = Path(user_home) / ".yadm"
        if not yadm_dir.exists():
            logger.warning(f"yadm directory not found for {linux_username}")
            return False

        # Run yadm status
        cmd = ["yadm", "status"]
        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        result = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=user_home,
        )

        is_healthy = result.returncode == 0
        logger.info(
            f"yadm setup verification for {linux_username}: "
            f"{'OK' if is_healthy else 'FAILED'}"
        )
        return is_healthy

    except Exception as exc:
        logger.error(f"Failed to verify yadm setup for {linux_username}: {exc}")
        return False


def check_yadm_installed() -> bool:
    """Check if yadm is installed on the system.

    Returns:
        True if yadm is available, False otherwise
    """
    try:
        result = subprocess.run(
            ["which", "yadm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False
