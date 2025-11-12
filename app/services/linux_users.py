"""Service for managing Linux OS user switching for tmux sessions.

Maps aiops web users to Linux system users and provides utilities for
resolving user identities and home directories.
"""

from __future__ import annotations

import pwd
from typing import NamedTuple, Optional

from flask import current_app


class LinuxUserInfo(NamedTuple):
    """Information about a Linux system user."""

    username: str
    uid: int
    gid: int
    home: str
    shell: str


def get_linux_user_info(username: str) -> Optional[LinuxUserInfo]:
    """Retrieve Linux system user information by username.

    Args:
        username: Linux username to look up

    Returns:
        LinuxUserInfo if user exists, None otherwise
    """
    try:
        user_info = pwd.getpwnam(username)
        return LinuxUserInfo(
            username=user_info.pw_name,
            uid=user_info.pw_uid,
            gid=user_info.pw_gid,
            home=user_info.pw_dir,
            shell=user_info.pw_shell,
        )
    except KeyError:
        return None


def resolve_linux_username(aiops_user: object) -> Optional[str]:
    """Resolve an aiops user to a Linux system username.

    Uses the configured mapping strategy to determine which Linux user
    should execute commands for this aiops user.

    First checks if the user has a per-user linux_username set, then attempts
    to load mapping from the database (SystemConfig), then falls back to app config.

    Args:
        aiops_user: User object from models.User

    Returns:
        Linux username string, or None if mapping fails

    Configuration:
        LINUX_USER_STRATEGY: 'mapping' (default) or 'direct'
        LINUX_USER_MAPPING: dict mapping email/username to Linux usernames
            (from database if available, otherwise from app config)
    """
    # Check if user has a per-user linux_username set (takes precedence)
    linux_username = getattr(aiops_user, "linux_username", None)
    if linux_username:
        return linux_username

    strategy = current_app.config.get("LINUX_USER_STRATEGY", "mapping")

    if strategy == "direct":
        # Use user.username as-is if it exists
        username = getattr(aiops_user, "username", None)
        if username:
            return username

    elif strategy == "mapping":
        # Try to load mapping from database first
        mapping = _load_mapping_from_db()

        # Fall back to config if database mapping is empty
        if not mapping:
            mapping = current_app.config.get("LINUX_USER_MAPPING", {})

        # Try email first
        email = getattr(aiops_user, "email", None)
        if email and email in mapping:
            return mapping[email]

        # Try username
        username = getattr(aiops_user, "username", None)
        if username and username in mapping:
            return mapping[username]

        # Try name (last resort)
        name = getattr(aiops_user, "name", None)
        if name and name in mapping:
            return mapping[name]

    return None


def _load_mapping_from_db() -> dict[str, str]:
    """Load Linux user mapping from the database.

    Returns empty dict if database is unavailable or mapping not configured.

    Returns:
        Dictionary mapping aiops user email to Linux username
    """
    try:
        from app.services.linux_user_config_service import get_linux_user_mapping

        return get_linux_user_mapping()
    except Exception:
        # Database not available, table doesn't exist, or other error
        return {}


def get_linux_user_for_aiops_user(aiops_user: object) -> Optional[LinuxUserInfo]:
    """Get Linux user info for an aiops user.

    Resolves the aiops user to a Linux username, then looks up the system
    user information.

    Args:
        aiops_user: User object from models.User

    Returns:
        LinuxUserInfo if mapping and user exist, None otherwise
    """
    linux_username = resolve_linux_username(aiops_user)
    if not linux_username:
        return None

    return get_linux_user_info(linux_username)


def get_user_home_directory(aiops_user: object) -> Optional[str]:
    """Get the home directory for an aiops user.

    Args:
        aiops_user: User object from models.User

    Returns:
        Home directory path, or None if user not found
    """
    user_info = get_linux_user_for_aiops_user(aiops_user)
    if user_info:
        return user_info.home

    return None


def validate_linux_user_exists(username: str) -> bool:
    """Check if a Linux system user exists.

    Args:
        username: Linux username to validate

    Returns:
        True if user exists, False otherwise
    """
    return get_linux_user_info(username) is not None


def should_use_login_shell() -> bool:
    """Determine if login shells should be used for sessions.

    When True, shells are invoked with -l/-i flags to load user configs
    (.bashrc, .profile, etc.).

    Returns:
        Boolean flag from config, defaults to True
    """
    return current_app.config.get("USE_LOGIN_SHELL", True)


def get_available_linux_users() -> list[str]:
    """Get list of available Linux system users.

    Retrieves all system users by reading /etc/passwd, filtering out system
    users (UID < 1000) to show only regular users.

    Returns:
        List of available Linux usernames sorted alphabetically
    """
    available_users = []
    try:
        with open("/etc/passwd") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) >= 3:
                    username = parts[0]
                    try:
                        uid = int(parts[2])
                        # Filter out system users (UID < 1000)
                        if uid >= 1000:
                            available_users.append(username)
                    except ValueError:
                        continue
    except Exception as e:
        current_app.logger.warning("Failed to get available Linux users: %s", e)

    return sorted(available_users)
