"""Service for managing per-user workspace directories.

Each user gets their own workspace for each project at:
/home/{linux_username}/workspace/{project_slug}/

This replaces the shared managed checkout model.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .linux_users import get_user_home_directory, resolve_linux_username

log = logging.getLogger(__name__)


class WorkspaceError(RuntimeError):
    """Raised when workspace operations fail."""


def _project_slug(project) -> str:
    """Generate a filesystem-safe slug from project name."""
    name = getattr(project, "name", "") or f"project-{project.id}"
    slug = name.lower().translate(str.maketrans({c: "-" for c in " ./\\:@"}))
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or f"project-{project.id}"


def get_workspace_path(project, user) -> Optional[Path]:
    """Get the workspace directory path for a user and project.

    Args:
        project: Project model instance
        user: User model instance

    Returns:
        Path to workspace directory, or None if user has no Linux mapping

    Example:
        /home/ivo/workspace/aiops/
    """
    home_dir = get_user_home_directory(user)
    if not home_dir:
        return None

    project_slug = _project_slug(project)
    workspace_path = Path(home_dir) / "workspace" / project_slug
    return workspace_path


def workspace_exists(project, user) -> bool:
    """Check if a workspace exists and is initialized (has .git).

    Args:
        project: Project model instance
        user: User model instance

    Returns:
        True if workspace exists and has .git directory
    """
    workspace_path = get_workspace_path(project, user)
    if not workspace_path:
        return False

    return workspace_path.exists() and (workspace_path / ".git").exists()


def initialize_workspace(project, user) -> Path:
    """Initialize a workspace by cloning the project repository.

    Args:
        project: Project model instance with repo_url and default_branch
        user: User model instance

    Returns:
        Path to initialized workspace

    Raises:
        WorkspaceError: If workspace cannot be created
    """
    from .git_service import build_project_git_env

    workspace_path = get_workspace_path(project, user)
    if not workspace_path:
        linux_username = resolve_linux_username(user)
        raise WorkspaceError(
            f"Cannot determine workspace path for user {getattr(user, 'email', 'unknown')}: "
            f"Linux username '{linux_username}' not found or has no home directory"
        )

    # Check if already initialized
    if workspace_exists(project, user):
        log.info(
            "Workspace already exists for project %s, user %s at %s",
            getattr(project, "name", project.id),
            getattr(user, "email", user.id),
            workspace_path,
        )
        return workspace_path

    # Create workspace directory
    try:
        workspace_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkspaceError(f"Failed to create workspace directory: {exc}") from exc

    # Clone repository
    try:
        from git import Repo

        env = build_project_git_env(project)
        Repo.clone_from(
            project.repo_url,
            workspace_path,
            branch=project.default_branch,
            env=env or None,
        )
        log.info(
            "Initialized workspace for project %s, user %s at %s",
            getattr(project, "name", project.id),
            getattr(user, "email", user.id),
            workspace_path,
        )
        return workspace_path
    except Exception as exc:
        # Clean up on failure
        if workspace_path.exists() and not (workspace_path / ".git").exists():
            import shutil

            shutil.rmtree(workspace_path, ignore_errors=True)
        raise WorkspaceError(f"Failed to clone repository: {exc}") from exc


def get_workspace_status(project, user) -> dict[str, any]:
    """Get status information about a workspace.

    Args:
        project: Project model instance
        user: User model instance

    Returns:
        Dictionary with workspace status:
        - exists: bool
        - path: str or None
        - has_git: bool
        - error: str or None
    """
    workspace_path = get_workspace_path(project, user)

    if not workspace_path:
        return {
            "exists": False,
            "path": None,
            "has_git": False,
            "error": "Cannot determine workspace path (Linux user not found)",
        }

    exists = workspace_path.exists()
    has_git = exists and (workspace_path / ".git").exists()

    return {
        "exists": exists,
        "path": str(workspace_path),
        "has_git": has_git,
        "error": None,
    }


__all__ = [
    "WorkspaceError",
    "get_workspace_path",
    "workspace_exists",
    "initialize_workspace",
    "get_workspace_status",
]
