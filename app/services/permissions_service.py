"""
Service for checking and fixing filesystem permissions on crucial aiops shared resources.

This ensures that all users can access shared resources like SSH keys, AI tool configs,
and the database. Per-user workspaces are not checked as they are owned by individual
users in their home directories.
"""

import grp
import logging
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .sudo_service import SudoError, chgrp, chmod

logger = logging.getLogger(__name__)


class PermissionsError(Exception):
    """Base exception for permissions service errors."""


@dataclass
class PermissionRule:
    """Defines expected permissions for a path."""

    path: Path
    mode: int  # octal mode like 0o2775
    group: str
    is_file: bool = False
    recursive: bool = True
    description: str = ""


@dataclass
class PermissionIssue:
    """Describes a permission issue found during checks."""

    path: Path
    issue_type: Literal["mode", "group", "missing"]
    expected: str
    actual: str
    description: str


@dataclass
class PermissionCheckResult:
    """Result of checking and optionally fixing permissions."""

    checked: int = 0
    issues_found: int = 0
    issues_fixed: int = 0
    errors: list[str] = field(default_factory=list)
    issues: list[PermissionIssue] = field(default_factory=list)


def get_permission_rules(instance_path: Path) -> list[PermissionRule]:
    """
    Return the list of permission rules for crucial aiops shared resources.

    Shared resources need to be readable/writable by all syseng group members:
    - agents/, codex/, gemini/, claude/: AI tool configs (per-user subdirectories)
    - app.db: database file
    - current_branch.txt, tmux_tools.json: metadata files

    SSH keys need restricted access but readable by group:
    - keys/: SSH private keys (0o640 for files, 0o750 for directory)

    NOTE: Per-user workspaces (~/workspace/) are NOT checked as they are owned
    by individual users in their home directories.
    """
    return [
        # AI tool configuration directories
        PermissionRule(
            path=instance_path / "agents",
            mode=0o2775,
            group="syseng",
            recursive=True,
            description="AI agent configurations",
        ),
        PermissionRule(
            path=instance_path / "codex",
            mode=0o2775,
            group="syseng",
            recursive=True,
            description="Codex configurations",
        ),
        PermissionRule(
            path=instance_path / "gemini",
            mode=0o2775,
            group="syseng",
            recursive=True,
            description="Gemini configurations",
        ),
        PermissionRule(
            path=instance_path / "claude",
            mode=0o2775,
            group="syseng",
            recursive=True,
            description="Claude configurations",
        ),
        # Database file
        PermissionRule(
            path=instance_path / "app.db",
            mode=0o664,  # -rw-rw-r--
            group="syseng",
            is_file=True,
            description="SQLite database",
        ),
        # Metadata files
        PermissionRule(
            path=instance_path / "current_branch.txt",
            mode=0o664,
            group="syseng",
            is_file=True,
            description="Current branch tracker",
        ),
        PermissionRule(
            path=instance_path / "tmux_tools.json",
            mode=0o664,
            group="syseng",
            is_file=True,
            description="tmux tools metadata",
        ),
        PermissionRule(
            path=instance_path / "known_hosts",
            mode=0o664,
            group="syseng",
            is_file=True,
            description="SSH known hosts",
        ),
        PermissionRule(
            path=instance_path / "tmux.conf",
            mode=0o664,
            group="syseng",
            is_file=True,
            description="tmux configuration",
        ),
        # SSH keys directory - restricted but group readable
        PermissionRule(
            path=instance_path / "keys",
            mode=0o2750,  # drwxr-s---
            group="syseng",
            recursive=True,
            description="SSH private keys (restricted access)",
        ),
    ]


def _check_path_permissions(
    path: Path,
    expected_mode: int,
    expected_group: str,
) -> list[PermissionIssue]:
    """Check if a path has the expected permissions and group."""
    issues = []

    if not path.exists():
        issues.append(
            PermissionIssue(
                path=path,
                issue_type="missing",
                expected="exists",
                actual="missing",
                description=f"Path does not exist: {path}",
            )
        )
        return issues

    # Check mode
    actual_mode = path.stat().st_mode
    actual_mode_masked = stat.S_IMODE(actual_mode)
    if actual_mode_masked != expected_mode:
        issues.append(
            PermissionIssue(
                path=path,
                issue_type="mode",
                expected=oct(expected_mode),
                actual=oct(actual_mode_masked),
                description=f"Incorrect mode: {oct(actual_mode_masked)} (expected {oct(expected_mode)})",
            )
        )

    # Check group
    actual_gid = path.stat().st_gid
    try:
        actual_group = grp.getgrgid(actual_gid).gr_name
        if actual_group != expected_group:
            issues.append(
                PermissionIssue(
                    path=path,
                    issue_type="group",
                    expected=expected_group,
                    actual=actual_group,
                    description=f"Incorrect group: {actual_group} (expected {expected_group})",
                )
            )
    except KeyError:
        issues.append(
            PermissionIssue(
                path=path,
                issue_type="group",
                expected=expected_group,
                actual=f"gid:{actual_gid}",
                description=f"Unknown group GID: {actual_gid}",
            )
        )

    return issues


def check_permissions(instance_path: Path) -> PermissionCheckResult:
    """
    Check permissions on all crucial aiops folders without making changes.

    Returns a result object with details of any issues found.
    """
    result = PermissionCheckResult()
    rules = get_permission_rules(instance_path)

    for rule in rules:
        try:
            if not rule.path.exists():
                result.issues.append(
                    PermissionIssue(
                        path=rule.path,
                        issue_type="missing",
                        expected="exists",
                        actual="missing",
                        description=f"{rule.description}: path does not exist",
                    )
                )
                result.issues_found += 1
                continue

            # Check the root path
            issues = _check_path_permissions(rule.path, rule.mode, rule.group)
            result.issues.extend(issues)
            result.checked += 1

            # If recursive and is a directory, check all children
            if rule.recursive and rule.path.is_dir():
                for child in rule.path.rglob("*"):
                    # Files in keys/ directory get more restrictive permissions
                    if rule.path.name == "keys" and child.is_file():
                        file_mode = 0o640  # -rw-r-----
                    else:
                        file_mode = 0o664 if child.is_file() else rule.mode

                    child_issues = _check_path_permissions(child, file_mode, rule.group)
                    result.issues.extend(child_issues)
                    result.checked += 1

        except Exception as exc:
            logger.exception("Error checking permissions for %s", rule.path)
            result.errors.append(f"{rule.path}: {exc}")

    result.issues_found = len(result.issues)
    return result


def fix_permissions(instance_path: Path) -> PermissionCheckResult:
    """
    Fix permissions on all crucial aiops folders using sudo.

    This function should be run as a user with sudo privileges.
    It will use sudo to change ownership and permissions as needed.

    Returns a result object with details of checks and fixes applied.
    """
    result = PermissionCheckResult()
    rules = get_permission_rules(instance_path)

    for rule in rules:
        try:
            if not rule.path.exists():
                result.errors.append(f"{rule.path}: path does not exist, cannot fix")
                result.issues_found += 1
                continue

            # Fix the root path first
            issues = _check_path_permissions(rule.path, rule.mode, rule.group)
            result.checked += 1

            if issues:
                result.issues_found += len(issues)
                try:
                    _fix_path_permissions(rule.path, rule.mode, rule.group)
                    result.issues_fixed += len(issues)
                except Exception as exc:
                    logger.exception("Failed to fix permissions for %s", rule.path)
                    result.errors.append(f"{rule.path}: {exc}")

            # If recursive and is a directory, fix all children
            if rule.recursive and rule.path.is_dir():
                for child in rule.path.rglob("*"):
                    # Files in keys/ directory get more restrictive permissions
                    if rule.path.name == "keys" and child.is_file():
                        file_mode = 0o640  # -rw-r-----
                    else:
                        file_mode = 0o664 if child.is_file() else rule.mode

                    child_issues = _check_path_permissions(child, file_mode, rule.group)
                    result.checked += 1

                    if child_issues:
                        result.issues_found += len(child_issues)
                        try:
                            _fix_path_permissions(child, file_mode, rule.group)
                            result.issues_fixed += len(child_issues)
                        except Exception as exc:
                            logger.exception("Failed to fix permissions for %s", child)
                            result.errors.append(f"{child}: {exc}")

        except Exception as exc:
            logger.exception("Error processing rule for %s", rule.path)
            result.errors.append(f"{rule.path}: {exc}")

    return result


def _fix_path_permissions(path: Path, mode: int, group: str) -> None:
    """Fix permissions and group ownership for a single path using sudo."""
    try:
        chgrp(str(path), group)
    except SudoError as exc:
        raise PermissionsError(f"Failed to change group to {group}: {exc}") from exc

    try:
        chmod(str(path), mode)
    except SudoError as exc:
        raise PermissionsError(f"Failed to change mode to {oct(mode)}: {exc}") from exc

    logger.info("Fixed permissions for %s: mode=%s group=%s", path, oct(mode), group)
