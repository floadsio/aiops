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

    Args:
        aiops_user: User object from models.User

    Returns:
        Linux username string, or None if mapping fails

    Configuration:
        LINUX_USER_STRATEGY: 'mapping' (default) or 'direct'
        LINUX_USER_MAPPING: dict mapping email/username to Linux usernames
    """
    strategy = current_app.config.get("LINUX_USER_STRATEGY", "mapping")

    if strategy == "direct":
        # Use user.username as-is if it exists
        username = getattr(aiops_user, "username", None)
        if username:
            return username

    elif strategy == "mapping":
        # Look up in explicit mapping
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
