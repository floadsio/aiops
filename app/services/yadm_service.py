"""yadm (Yet Another Dotfiles Manager) service for managing user configuration files.

This service handles:
- Cloning and managing yadm dotfiles repositories
- GPG key management for encrypted files
- Bootstrap script execution
- File encryption/decryption
"""

import fnmatch
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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
    passphrase: Optional[str] = None,
) -> None:
    """Decrypt yadm-encrypted files after bootstrap.

    Args:
        linux_username: Linux username (for sudo execution)
        user_home: User's home directory
        passphrase: Optional passphrase for decrypting encrypted files

    Raises:
        YadmServiceError: If decryption fails
    """
    try:
        cmd = ["yadm", "decrypt"]

        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd

        # Prepare stdin if passphrase is provided
        stdin_data = None
        if passphrase:
            stdin_data = f"{passphrase}\n"

        result = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            input=stdin_data,
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


def initialize_yadm_for_user(
    user: User, repo_url: str, repo_branch: str = "main"
) -> dict[str, str]:
    """Initialize yadm for a user's home directory.

    This function:
    1. Clones the dotfiles repo to ~/.yadm/
    2. Runs yadm bootstrap
    3. Runs yadm decrypt (if encrypted files exist)

    Args:
        user: User model instance
        repo_url: Dotfiles repository URL (e.g., git@gitlab.com:floads/dotfiles.git)
        repo_branch: Branch to clone (default: "main")

    Returns:
        Dictionary with status and messages

    Raises:
        YadmServiceError: If initialization fails
    """
    linux_username = user.email.split("@")[0]
    user_home = f"/home/{linux_username}"
    yadm_repo_dir = f"{user_home}/.local/share/yadm/repo.git"

    try:
        # Check if yadm is already initialized
        if Path(yadm_repo_dir).exists():
            logger.info(f"yadm already initialized for {user.email}, updating remote and pulling...")
            # Update the remote URL in case it changed
            set_remote_cmd = [
                "yadm", "remote", "set-url", "origin", repo_url
            ]
            sudo_cmd = ["sudo", "-E", "-u", linux_username, "-H"] + set_remote_cmd
            result = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=user_home,
            )
            if result.returncode != 0:
                logger.warning(f"Failed to update yadm remote: {result.stderr or result.stdout}")

            # Pull latest changes
            pull_cmd = [
                "yadm", "pull", "--ff-only"
            ]
            sudo_cmd = ["sudo", "-E", "-u", linux_username, "-H"] + pull_cmd
            result = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=user_home,
            )
            if result.returncode != 0:
                logger.warning(f"Failed to pull yadm updates: {result.stderr or result.stdout}")
        else:
            # 1. Clone dotfiles to ~/.yadm
            logger.info(f"Initializing yadm for user {user.email}")

            clone_cmd = [
                "yadm", "clone",
                f"--branch={repo_branch}",
                repo_url
            ]
            sudo_cmd = ["sudo", "-E", "-u", linux_username, "-H"] + clone_cmd

            result = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes for clone
                cwd=user_home,
            )

            if result.returncode != 0:
                raise YadmServiceError(
                    f"yadm clone failed: {result.stderr or result.stdout}"
                )

        logger.info(f"Successfully cloned dotfiles for {user.email}")

        # 2. Run yadm bootstrap
        try:
            apply_yadm_bootstrap(linux_username, user_home)
            logger.info(f"yadm bootstrap completed for {user.email}")
        except YadmServiceError as e:
            # Bootstrap is non-critical
            logger.warning(f"yadm bootstrap had issues: {e}")

        # 3. Run yadm decrypt
        try:
            yadm_decrypt(linux_username, user_home)
            logger.info(f"yadm decrypt completed for {user.email}")
        except YadmServiceError as e:
            # Decrypt is non-critical if no encrypted files
            logger.warning(f"yadm decrypt had issues: {e}")

        return {
            "status": "success",
            "message": f"yadm initialized successfully for {user.email}",
            "home": user_home,
            "yadm_dir": f"{user_home}/.yadm",
        }

    except YadmServiceError:
        raise
    except Exception as exc:
        logger.exception(f"Unexpected error initializing yadm for {user.email}")
        raise YadmServiceError(
            f"Failed to initialize yadm for {user.email}: {exc}"
        ) from exc


def pull_and_apply_yadm_update(
    linux_username: str,
    user_home: str,
) -> dict[str, Any]:
    """Pull latest changes from dotfiles repo and re-run bootstrap.

    This combines pull + bootstrap + decrypt into a single update operation.

    Args:
        linux_username: Linux username (for sudo execution)
        user_home: User's home directory

    Returns:
        Dictionary with status, message, and timestamp

    Raises:
        YadmServiceError: If pull fails (bootstrap/decrypt failures are non-critical)
    """
    try:
        # 1. Pull from remote
        pull_cmd = ["yadm", "pull"]
        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + pull_cmd
        result = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=user_home,
        )

        if result.returncode != 0:
            raise YadmServiceError(
                f"yadm pull failed: {result.stderr or result.stdout}"
            )

        logger.info(f"Pulled latest yadm changes for user {linux_username}")

        # 2. Run bootstrap (non-critical)
        try:
            apply_yadm_bootstrap(linux_username, user_home)
        except YadmServiceError as e:
            logger.warning(f"Bootstrap had issues for {linux_username}: {e}")

        # 3. Run decrypt (non-critical)
        try:
            yadm_decrypt(linux_username, user_home)
        except YadmServiceError as e:
            logger.warning(f"Decrypt had issues for {linux_username}: {e}")

        return {
            "status": "success",
            "message": "Dotfiles updated successfully",
            "timestamp": datetime.utcnow().isoformat(),
        }

    except subprocess.TimeoutExpired as exc:
        raise YadmServiceError(f"yadm pull timed out: {exc}") from exc
    except YadmServiceError:
        raise
    except Exception as exc:
        logger.exception(f"Failed to update yadm for {linux_username}")
        raise YadmServiceError(f"Update failed: {exc}") from exc


def get_yadm_managed_files(
    linux_username: str,
    user_home: str,
) -> dict[str, Any]:
    """Get list of files managed by yadm repository.

    Args:
        linux_username: Linux username
        user_home: User's home directory

    Returns:
        Dictionary with tracked, untracked, encrypted, and modified file lists
    """
    try:
        result = {
            "tracked": [],
            "untracked": [],
            "encrypted": [],
            "modified": [],
            "error": None,
        }

        # Get tracked files: yadm list -a
        cmd = ["yadm", "list", "-a"]
        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        res = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=user_home,
        )

        if res.returncode == 0:
            result["tracked"] = [f.strip() for f in res.stdout.splitlines() if f.strip()]

        # Get encrypted patterns from .yadm/encrypt
        encrypt_patterns_file = Path(user_home) / ".yadm" / "encrypt"
        encrypted_files = []
        if encrypt_patterns_file.exists():
            try:
                patterns = encrypt_patterns_file.read_text().splitlines()
                # Match tracked files against patterns
                for pattern in patterns:
                    if pattern.strip():
                        for tracked_file in result["tracked"]:
                            if fnmatch.fnmatch(tracked_file, pattern.strip()):
                                if tracked_file not in encrypted_files:
                                    encrypted_files.append(tracked_file)
            except Exception as e:
                logger.warning(
                    f"Failed to parse encrypt patterns for {linux_username}: {e}"
                )

        result["encrypted"] = encrypted_files

        # Get modified files from git status
        try:
            cmd = ["yadm", "status", "-s"]
            sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
            res = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=user_home,
            )

            if res.returncode == 0:
                modified = []
                for line in res.stdout.splitlines():
                    if line.strip():
                        # Format: "XY filename"
                        parts = line.strip().split(maxsplit=1)
                        if len(parts) == 2:
                            modified.append(parts[1])
                result["modified"] = modified
        except Exception as e:
            logger.warning(f"Failed to get modified files for {linux_username}: {e}")

        return result

    except Exception as exc:
        logger.error(f"Failed to get yadm file list for {linux_username}: {exc}")
        return {
            "tracked": [],
            "untracked": [],
            "encrypted": [],
            "modified": [],
            "error": str(exc),
        }


def get_yadm_git_status(
    linux_username: str,
    user_home: str,
) -> dict[str, Any]:
    """Get git status information for yadm repository.

    Args:
        linux_username: Linux username
        user_home: User's home directory

    Returns:
        Dictionary with branch, remote, commits, and status information
    """
    try:
        result = {
            "branch": None,
            "remote_url": None,
            "commits_ahead": 0,
            "commits_behind": 0,
            "dirty": False,
            "status_summary": "Unknown",
            "last_pull": None,
            "error": None,
        }

        # Get current branch
        cmd = ["yadm", "rev-parse", "--abbrev-ref", "HEAD"]
        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        res = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=user_home,
        )
        if res.returncode == 0:
            result["branch"] = res.stdout.strip()

        # Get remote URL
        cmd = ["yadm", "remote", "get-url", "origin"]
        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        res = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=user_home,
        )
        if res.returncode == 0:
            result["remote_url"] = res.stdout.strip()

        # Get commits ahead/behind
        try:
            cmd = ["yadm", "rev-list", "--left-right", "--count", "@{u}...HEAD"]
            sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
            res = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=user_home,
            )
            if res.returncode == 0:
                parts = res.stdout.strip().split()
                if len(parts) == 2:
                    result["commits_behind"] = int(parts[0])
                    result["commits_ahead"] = int(parts[1])
        except Exception:
            pass  # May not have tracking branch

        # Get git status (dirty check)
        cmd = ["yadm", "status", "--porcelain"]
        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        res = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=user_home,
        )
        if res.returncode == 0:
            result["dirty"] = bool(res.stdout.strip())

        # Set status summary
        if result["dirty"]:
            result["status_summary"] = "Modified"
        elif result["commits_ahead"] > 0:
            result["status_summary"] = "Ahead"
        elif result["commits_behind"] > 0:
            result["status_summary"] = "Behind"
        else:
            result["status_summary"] = "Clean"

        # Get last pull time from git reflog
        try:
            cmd = ["yadm", "reflog", "-1", "--format=%ai"]
            sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
            res = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=user_home,
            )
            if res.returncode == 0:
                result["last_pull"] = res.stdout.strip()
        except Exception:
            pass

        return result

    except Exception as exc:
        logger.error(f"Failed to get git status for {linux_username}: {exc}")
        return {
            "branch": None,
            "remote_url": None,
            "commits_ahead": 0,
            "commits_behind": 0,
            "dirty": False,
            "status_summary": "Error",
            "last_pull": None,
            "error": str(exc),
        }


def get_yadm_bootstrap_info(
    linux_username: str,
    user_home: str,
) -> dict[str, Any]:
    """Get bootstrap script information and status.

    Args:
        linux_username: Linux username
        user_home: User's home directory

    Returns:
        Dictionary with bootstrap script info
    """
    try:
        result = {
            "exists": False,
            "executable": False,
            "last_run": None,
            "has_bootstrap_dir": False,
            "bootstrap_scripts": [],
            "error": None,
        }

        bootstrap_file = Path(user_home) / ".yadm" / "bootstrap"
        if bootstrap_file.exists():
            result["exists"] = True
            result["executable"] = os.access(bootstrap_file, os.X_OK)

            # Get last modification time
            try:
                mtime = bootstrap_file.stat().st_mtime
                result["last_run"] = datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                pass

        # Check for bootstrap.d directory
        bootstrap_dir = Path(user_home) / ".yadm" / "bootstrap.d"
        if bootstrap_dir.exists() and bootstrap_dir.is_dir():
            result["has_bootstrap_dir"] = True
            try:
                scripts = sorted(
                    [f.name for f in bootstrap_dir.iterdir() if f.is_file()]
                )
                result["bootstrap_scripts"] = scripts
            except Exception as e:
                logger.warning(
                    f"Failed to list bootstrap.d scripts for {linux_username}: {e}"
                )

        return result

    except Exception as exc:
        logger.error(f"Failed to get bootstrap info for {linux_username}: {exc}")
        return {
            "exists": False,
            "executable": False,
            "last_run": None,
            "has_bootstrap_dir": False,
            "bootstrap_scripts": [],
            "error": str(exc),
        }


def _find_yadm_config_via_sudo(linux_username: str, user_home: str) -> Optional[str]:
    """Find yadm config directory via sudo when permissions restrict direct access.

    Uses sudo to run find command as the user to locate yadm config directories.
    Returns the first yadm config directory found, prioritizing yadm-* variants.
    The find command has already verified the directory exists, so we don't need
    to check again (which would fail with PermissionError for restricted access).
    """
    try:
        # Find all yadm config directories under ~/.config
        cmd = ["find", f"{user_home}/.config", "-maxdepth", "1", "-name", "yadm*", "-type", "d"]
        sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
        result = subprocess.run(
            sudo_cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0 and result.stdout:
            dirs = [d.strip() for d in result.stdout.splitlines() if d.strip()]

            # Prioritize yadm-* variants (e.g., yadm-floads) over plain yadm
            # Variants are variant names like "yadm-floads", plain is just "yadm"
            dirs_sorted = sorted(dirs, key=lambda x: (Path(x).name == "yadm", x))

            # Return first one - find command already verified it exists
            # We can't check contents via Path due to permission restrictions,
            # but find verified it's a directory that exists
            if dirs_sorted:
                return dirs_sorted[0]
    except Exception as e:
        logger.debug(f"Could not find yadm config via sudo for {linux_username}: {e}")

    return None


def _find_yadm_dir(user_home: str, linux_username: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """Find yadm directory (standard or custom).

    Returns:
        Tuple of (yadm_config_dir, yadm_data_dir) or (None, None) if not found.
        Handles hybrid setups where config and data may be in different locations.
        For standard yadm: (~/.yadm, ~/.local/share/yadm)
        For custom yadm: (~/.config/yadm-floads, ~/.local/share/yadm-floads)
        For hybrid: (~/.config/yadm-floads config, ~/.local/share/yadm data)
    """
    # First, find which data directory has the actual repo.git
    share_dir = Path(user_home) / ".local" / "share"
    repo_data_dir = None

    try:
        if share_dir.exists():
            # Check all yadm* directories in ~/.local/share for repo.git
            for item in sorted(share_dir.iterdir()):
                try:
                    if item.is_dir() and item.name.startswith("yadm"):
                        repo_path = item / "repo.git"
                        if repo_path.exists():
                            repo_data_dir = item
                            break  # Found it, stop searching
                except (PermissionError, OSError):
                    # Skip directories we can't access
                    continue
    except (PermissionError, OSError):
        # Can't access share directory
        return (None, None)

    if not repo_data_dir:
        # No initialized yadm found
        return (None, None)

    # Now find the matching config directory
    # Prefer config with same yadm variant name AND content, fallback to any non-empty variant
    repo_variant = repo_data_dir.name  # e.g., "yadm" or "yadm-floads"

    config_dir = Path(user_home) / ".config"
    config_found = None

    try:
        if config_dir.exists():
            # Look for matching config: ~/.config/yadm or ~/.config/yadm-floads
            matching_config = config_dir / repo_variant
            try:
                # .exists() can throw PermissionError if parent dir is not accessible
                try:
                    if matching_config.exists():
                        if (
                            matching_config.is_dir()
                            and any(matching_config.iterdir())
                        ):
                            # Found matching config with content for this repo
                            return (str(matching_config), str(repo_data_dir))
                except (PermissionError, OSError):
                    # Can't access matching config, skip to variant search
                    pass
            except (PermissionError, OSError):
                pass

            # If repo is at standard location but no matching config with content,
            # try to find any yadm* config directory with content (for hybrid setups)
            # Even if we can't enumerate .config, try checking specific yadm variants
            if repo_variant == "yadm":
                # First try to enumerate if possible
                try:
                    for item in sorted(config_dir.iterdir()):
                        try:
                            if (
                                item.is_dir()
                                and item.name.startswith("yadm")
                                and any(item.iterdir())
                            ):
                                return (str(item), str(repo_data_dir))
                        except (PermissionError, OSError):
                            # Skip directories we can't access
                            continue
                except (PermissionError, OSError):
                    # Can't enumerate config directory directly
                    # If we have linux_username, try via sudo for permission-restricted access
                    if linux_username:
                        config_found = _find_yadm_config_via_sudo(linux_username, user_home)
                        if config_found:
                            return (config_found, str(repo_data_dir))

                    # Fall back to trying common yadm variants manually
                    for variant_name in ["yadm-floads", "yadm-main", "yadm-backup"]:
                        variant_config = config_dir / variant_name
                        try:
                            try:
                                variant_exists = variant_config.exists()
                            except (PermissionError, OSError):
                                # Can't check if variant exists
                                continue

                            if (
                                variant_exists
                                and variant_config.is_dir()
                                and any(variant_config.iterdir())
                            ):
                                return (str(variant_config), str(repo_data_dir))
                        except (PermissionError, OSError):
                            continue
    except (PermissionError, OSError):
        # Can't access config directory at all
        pass

    # Return repo location with standard config location
    standard_config = Path(user_home) / ".yadm"
    return (str(standard_config), str(repo_data_dir))


def get_yadm_encryption_status(
    linux_username: str,
    user_home: str,
    user: Optional[User] = None,
) -> dict[str, Any]:
    """Get encryption status and GPG key information.

    Args:
        linux_username: Linux username
        user_home: User's home directory
        user: Optional User model instance for GPG key info

    Returns:
        Dictionary with encryption status
    """
    try:
        result = {
            "has_encrypt_patterns": False,
            "encrypted_file_count": 0,
            "encrypted_patterns": [],
            "encrypted_files": [],
            "archive_exists": False,
            "gpg_key_configured": False,
            "gpg_key_id": None,
            "gpg_key_imported": False,
            "error": None,
        }

        # Detect yadm directory (standard or custom)
        yadm_config_dir, yadm_data_dir = _find_yadm_dir(user_home, linux_username)
        if not yadm_config_dir or not yadm_data_dir:
            logger.debug(f"No yadm configuration found for {linux_username}")
            return result

        # Check for encrypt patterns
        encrypt_file = Path(yadm_config_dir) / "encrypt"
        if encrypt_file.exists():
            result["has_encrypt_patterns"] = True
            try:
                patterns = encrypt_file.read_text().splitlines()
                # Get non-empty patterns
                non_empty_patterns = [p.strip() for p in patterns if p.strip()]
                result["encrypted_file_count"] = len(non_empty_patterns)
                result["encrypted_patterns"] = non_empty_patterns
            except Exception as e:
                logger.warning(
                    f"Failed to read encrypt patterns for {linux_username}: {e}"
                )

        # Check for archive and try to list encrypted files
        # For hybrid setups, also check variant directories (e.g., yadm-floads)
        archive_paths = [Path(yadm_data_dir) / "archive"]

        # If config is a variant (e.g., yadm-floads), also check its data directory
        config_name = Path(yadm_config_dir).name if yadm_config_dir else None
        if config_name and config_name.startswith("yadm") and config_name != "yadm":
            variant_data_dir = Path(user_home) / ".local" / "share" / config_name
            if variant_data_dir.exists():
                variant_archive = variant_data_dir / "archive"
                if variant_archive not in archive_paths:
                    archive_paths.append(variant_archive)

        for archive_path in archive_paths:
            if archive_path.exists():
                result["archive_exists"] = True
                try:
                    # For hybrid/custom setups, determine the correct YADM_DIR
                    # YADM_DIR should point to the config directory for yadm to find the archive
                    config_name = Path(yadm_config_dir).name if yadm_config_dir else "yadm"

                    # Build environment for yadm command
                    env = os.environ.copy()
                    env["HOME"] = user_home

                    # Set YADM_DIR to help yadm find the correct config and archive
                    # For custom setups like yadm-floads, this tells yadm where to look
                    if config_name != "yadm" and yadm_config_dir:
                        env["YADM_DIR"] = yadm_config_dir

                    # Try to use yadm decrypt -l to list files in archive
                    # With proper YADM_DIR, this should find archives in custom locations
                    cmd = ["yadm", "decrypt", "-l"]
                    sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd

                    res = subprocess.run(
                        sudo_cmd,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=user_home,
                        env=env,
                    )
                    if res.returncode == 0 and res.stdout:
                        # Parse the output to get file list
                        encrypted_files = [
                            line.strip()
                            for line in res.stdout.splitlines()
                            if line.strip()
                        ]
                        result["encrypted_files"] = encrypted_files
                        break  # Got files, stop checking other archives
                    else:
                        # If yadm decrypt fails, log but don't treat as error
                        # Archive exists but may be encrypted or require password
                        logger.debug(
                            f"Could not list archive files for {linux_username} "
                            f"from {archive_path}: {res.stderr}"
                        )
                except Exception as e:
                    logger.debug(
                        f"Could not list archive files for {linux_username}: {e}"
                    )

        # Check for GPG key in database
        if user:
            result["gpg_key_configured"] = bool(user.gpg_private_key_encrypted)
            if user.gpg_key_id:
                result["gpg_key_id"] = user.gpg_key_id

                # Check if GPG key is imported in user's keyring
                try:
                    cmd = ["gpg", "--list-keys", user.gpg_key_id]
                    sudo_cmd = ["sudo", "-u", linux_username, "-H"] + cmd
                    res = subprocess.run(
                        sudo_cmd,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        cwd=user_home,
                    )
                    result["gpg_key_imported"] = res.returncode == 0
                except Exception as e:
                    logger.warning(
                        f"Failed to check GPG key import for {linux_username}: {e}"
                    )

        return result

    except Exception as exc:
        logger.error(f"Failed to get encryption status for {linux_username}: {exc}")
        return {
            "has_encrypt_patterns": False,
            "encrypted_file_count": 0,
            "encrypted_patterns": [],
            "encrypted_files": [],
            "archive_exists": False,
            "gpg_key_configured": False,
            "gpg_key_id": None,
            "gpg_key_imported": False,
            "error": str(exc),
        }


def get_full_yadm_status(user: User) -> dict[str, Any]:
    """Get complete yadm status snapshot (combines all status functions).

    Args:
        user: User model instance

    Returns:
        Comprehensive status dictionary combining all status info

    Raises:
        YadmServiceError: If user home directory cannot be determined
    """
    linux_username = user.email.split("@")[0]
    user_home = f"/home/{linux_username}"

    try:
        # Check if yadm is initialized (standard or custom)
        yadm_config_dir, yadm_data_dir = _find_yadm_dir(user_home, linux_username)
        is_initialized = yadm_config_dir is not None and (
            Path(yadm_data_dir) / "repo.git"
        ).exists()

        result = {
            "user_email": user.email,
            "linux_username": linux_username,
            "user_home": user_home,
            "is_initialized": is_initialized,
            "yadm_installed": check_yadm_installed(),
            "timestamp": datetime.utcnow().isoformat(),
            "files": {},
            "git": {},
            "bootstrap": {},
            "encryption": {},
            "error": None,
        }

        if is_initialized:
            # Get all status info
            result["files"] = get_yadm_managed_files(linux_username, user_home)
            result["git"] = get_yadm_git_status(linux_username, user_home)
            result["bootstrap"] = get_yadm_bootstrap_info(linux_username, user_home)
            result["encryption"] = get_yadm_encryption_status(
                linux_username, user_home, user
            )

        return result

    except Exception as exc:
        logger.exception(f"Failed to get full yadm status for {user.email}")
        return {
            "user_email": user.email,
            "linux_username": linux_username,
            "user_home": user_home,
            "is_initialized": False,
            "yadm_installed": check_yadm_installed(),
            "timestamp": datetime.utcnow().isoformat(),
            "files": {},
            "git": {},
            "bootstrap": {},
            "encryption": {},
            "error": str(exc),
        }
