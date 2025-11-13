"""Utilities for executing commands as different Linux users via sudo.

This module provides a clean interface for sudo operations throughout aiops,
with consistent error handling, timeout management, and logging.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


class SudoError(RuntimeError):
    """Raised when sudo operations fail."""


@dataclass
class SudoResult:
    """Result of a sudo command execution."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def run_as_user(
    username: str,
    command: list[str],
    *,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> SudoResult:
    """Execute a command as a different Linux user via sudo.

    Args:
        username: Linux username to run as
        command: Command and arguments to execute
        timeout: Timeout in seconds (default: 30)
        env: Environment variables to pass (via 'env' command)
        check: Raise SudoError if command fails (default: True)
        capture_output: Capture stdout/stderr (default: True)

    Returns:
        SudoResult with returncode, stdout, stderr

    Raises:
        SudoError: If check=True and command fails

    Example:
        >>> result = run_as_user('ivo', ['git', 'status'], timeout=10)
        >>> if result.success:
        ...     print(result.stdout)
    """
    # Build sudo command: sudo -n -u username [env KEY=VAL ...] command
    cmd = ["sudo", "-n", "-u", username]

    if env:
        cmd.append("env")
        for key, value in env.items():
            cmd.append(f"{key}={value}")

    cmd.extend(command)

    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True if capture_output else False,
            timeout=timeout,
        )

        sudo_result = SudoResult(
            returncode=result.returncode,
            stdout=result.stdout if capture_output else "",
            stderr=result.stderr if capture_output else "",
        )

        if check and not sudo_result.success:
            raise SudoError(
                f"Command failed as user {username}: {command[0]} "
                f"(exit {result.returncode})\n{result.stderr}"
            )

        return sudo_result

    except subprocess.TimeoutExpired as exc:
        raise SudoError(
            f"Command timed out after {timeout}s as user {username}: {command[0]}"
        ) from exc
    except FileNotFoundError as exc:
        raise SudoError(
            f"Command not found for user {username}: {command[0]}"
        ) from exc


def test_path(username: str, path: str, *, timeout: float = 5.0) -> bool:
    """Check if a path exists as a specific user.

    Args:
        username: Linux username to run as
        path: Path to check
        timeout: Timeout in seconds (default: 5)

    Returns:
        True if path exists, False otherwise
    """
    try:
        result = run_as_user(
            username,
            ["test", "-e", path],
            timeout=timeout,
            check=False,
        )
        return result.success
    except SudoError:
        return False


def mkdir(username: str, path: str, *, parents: bool = True, timeout: float = 10.0) -> None:
    """Create a directory as a specific user.

    Args:
        username: Linux username to run as
        path: Path to create
        parents: Create parent directories (default: True)
        timeout: Timeout in seconds (default: 10)

    Raises:
        SudoError: If directory creation fails
    """
    cmd = ["mkdir"]
    if parents:
        cmd.append("-p")
    cmd.append(path)

    run_as_user(username, cmd, timeout=timeout)


def chown(path: str, owner: str | None = None, group: str | None = None) -> None:
    """Change ownership of a file or directory.

    Args:
        path: Path to modify
        owner: New owner username (optional)
        group: New group name (optional)

    Raises:
        SudoError: If operation fails
    """
    if not owner and not group:
        raise ValueError("Must specify owner and/or group")

    ownership = ""
    if owner:
        ownership = owner
    if group:
        ownership += f":{group}"

    try:
        subprocess.run(
            ["sudo", "chown", ownership, str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as exc:
        raise SudoError(f"Failed to chown {path}: {exc.stderr}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SudoError(f"chown timed out for {path}") from exc


def chmod(path: str, mode: int, *, timeout: float = 10.0) -> None:
    """Change permissions of a file or directory.

    Args:
        path: Path to modify
        mode: Octal mode (e.g., 0o755)
        timeout: Timeout in seconds (default: 10)

    Raises:
        SudoError: If operation fails
    """
    mode_str = oct(mode)[2:]  # Convert 0o755 to '755'

    try:
        subprocess.run(
            ["sudo", "chmod", mode_str, str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        raise SudoError(f"Failed to chmod {path}: {exc.stderr}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SudoError(f"chmod timed out for {path}") from exc


def chgrp(path: str, group: str, *, timeout: float = 10.0) -> None:
    """Change group ownership of a file or directory.

    Args:
        path: Path to modify
        group: New group name
        timeout: Timeout in seconds (default: 10)

    Raises:
        SudoError: If operation fails
    """
    try:
        subprocess.run(
            ["sudo", "chgrp", group, str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        raise SudoError(f"Failed to chgrp {path}: {exc.stderr}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SudoError(f"chgrp timed out for {path}") from exc


def rm_rf(username: str, path: str, *, timeout: float = 30.0) -> None:
    """Recursively remove a directory as a specific user.

    Args:
        username: Linux username to run as
        path: Path to remove
        timeout: Timeout in seconds (default: 30)

    Raises:
        SudoError: If removal fails
    """
    run_as_user(username, ["rm", "-rf", path], timeout=timeout)


__all__ = [
    "SudoError",
    "SudoResult",
    "run_as_user",
    "test_path",
    "mkdir",
    "chown",
    "chmod",
    "chgrp",
    "rm_rf",
]
