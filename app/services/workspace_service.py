"""Service for managing per-user workspace directories.

Each user gets their own workspace for each project at:
/home/{linux_username}/workspace/{tenant_slug}/{project_slug}/

This replaces the shared managed checkout model.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Any, Optional

from .git_service import resolve_project_ssh_key_path, resolve_project_ssh_key_reference
from .linux_users import get_user_home_directory, resolve_linux_username
from .ssh_key_service import ssh_key_file_for_user
from .sudo_service import SudoError, mkdir, rm_rf, run_as_user, test_path

log = logging.getLogger(__name__)


class WorkspaceError(RuntimeError):
    """Raised when workspace operations fail."""


def _slugify(value: str, fallback: str) -> str:
    """Return a filesystem-safe slug for the provided value."""
    translation_map: dict[str, str | int] = {c: "-" for c in " ./\\:@"}
    slug = value.lower().translate(str.maketrans(translation_map))
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or fallback


def _project_slug(project) -> str:
    """Generate a filesystem-safe slug from project name."""
    name = getattr(project, "name", "") or f"project-{project.id}"
    return _slugify(name, f"project-{project.id}")


def _tenant_slug(project) -> str:
    """Generate a filesystem-safe slug for the owning tenant."""
    tenant = getattr(project, "tenant", None)
    tenant_name = getattr(tenant, "name", "") if tenant else ""
    tenant_id = getattr(project, "tenant_id", None)
    fallback = f"tenant-{tenant_id}" if tenant_id is not None else "tenant"
    return _slugify(tenant_name, fallback)


def _path_exists_for_user(path: Path, user) -> bool:
    """Check if a path exists, falling back to sudo when permissions block access."""
    try:
        return path.exists()
    except PermissionError:
        if not user:
            return False
        linux_username = resolve_linux_username(user)
        if not linux_username:
            return False
        return test_path(linux_username, str(path))


def _build_workspace_git_env(
    env: Optional[dict[str, str]] = None,
    *,
    ssh_key_path: str | None = None,
) -> dict[str, str]:
    """Ensure git commands accept new host keys automatically."""

    command = ["ssh"]
    if ssh_key_path:
        command.extend(["-i", shlex.quote(ssh_key_path), "-o", "IdentitiesOnly=yes"])
    command.extend(["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"])
    default_env = {"GIT_SSH_COMMAND": " ".join(command)}
    if not env:
        return default_env

    merged_env = dict(env)
    merged_env.setdefault("GIT_SSH_COMMAND", default_env["GIT_SSH_COMMAND"])
    return merged_env


def _project_key_accessible_to_user(
    linux_username: str,
    ssh_key_path: str,
) -> bool:
    """Return True if the target user can read the configured project key."""

    try:
        result = run_as_user(
            linux_username,
            ["test", "-r", ssh_key_path],
            timeout=5.0,
            check=False,
            capture_output=False,
        )
    except SudoError:
        return False

    return result.success


def _git_clone_via_sudo(
    linux_username: str,
    repo_url: str,
    target_path: str,
    branch: str,
    env: Optional[dict[str, str]] = None,
    *,
    ssh_key_path: str | None = None,
) -> None:
    """Clone a git repository using sudo to run as the target user.

    Args:
        linux_username: Linux username to run as
        repo_url: Git repository URL
        target_path: Path to clone into
        branch: Branch to check out
        env: Environment variables for git (e.g., SSH keys)

    Raises:
        WorkspaceError: If git clone fails
    """
    try:
        git_env = _build_workspace_git_env(env, ssh_key_path=ssh_key_path)
        run_as_user(
            linux_username,
            ["git", "clone", "--branch", branch, repo_url, target_path],
            env=git_env,
            timeout=300,  # 5 minutes for git clone
        )
    except SudoError as exc:
        raise WorkspaceError(str(exc)) from exc


def get_workspace_path(project, user) -> Optional[Path]:
    """Get the workspace directory path for a user and project.

    Args:
        project: Project model instance
        user: User model instance

    Returns:
        Path to workspace directory, or None if user has no Linux mapping

    Example:
        /home/<user>/workspace/<tenant>/<project>/
    """
    home_dir = get_user_home_directory(user)
    if not home_dir:
        return None

    project_slug = _project_slug(project)
    tenant_slug = _tenant_slug(project)
    workspace_root = Path(home_dir) / "workspace"
    preferred_path = workspace_root / tenant_slug / project_slug
    legacy_path = workspace_root / project_slug

    # Prefer the tenant-aware layout when it already exists, fall back to the legacy
    # single-directory layout for users who have not migrated yet.
    if _path_exists_for_user(preferred_path, user):
        return preferred_path
    if preferred_path != legacy_path and _path_exists_for_user(legacy_path, user):
        return legacy_path

    return preferred_path


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

    try:
        return workspace_path.exists() and (workspace_path / ".git").exists()
    except PermissionError:
        # Fall back to sudo check
        linux_username = resolve_linux_username(user)
        if not linux_username:
            return False
        exists = test_path(linux_username, str(workspace_path))
        has_git = exists and test_path(linux_username, str(workspace_path / ".git"))
        return exists and has_git


def _get_global_dotfile_settings() -> tuple[Optional[str], str]:
    """Get global dotfile settings from database.

    Returns:
        Tuple of (repo_url, branch) or (None, "main") if not configured
    """
    from ..models import SystemConfig

    repo_config = SystemConfig.query.filter_by(key="dotfile_repo_url").first()
    branch_config = SystemConfig.query.filter_by(key="dotfile_repo_branch").first()

    repo_url = repo_config.value.get("url") if repo_config and repo_config.value else None
    branch = branch_config.value.get("branch") if branch_config and branch_config.value else "main"

    return repo_url, branch


def initialize_workspace(project, user) -> Path:
    """Initialize a workspace by cloning the project repository.

    Args:
        project: Project model instance with repo_url and default_branch
        user: User model instance

    Returns:
        Path to initialized workspace

    Raises:
        WorkspaceError: If workspace cannot be created

    Note:
        When a project or tenant SSH key is available it will be used for the
        initial clone so shared credentials continue to work for per-user
        workspaces. If no managed key is configured, the user's own SSH setup
        in ~/.ssh/ is used instead.
    """
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

    # Create workspace directory using sudo as the target user
    linux_username = resolve_linux_username(user)
    if not linux_username:
        raise WorkspaceError(
            f"Cannot determine Linux username for user {getattr(user, 'email', 'unknown')}"
        )

    try:
        mkdir(linux_username, str(workspace_path))
    except SudoError as exc:
        raise WorkspaceError(str(exc)) from exc

    # Check for SSH key - prefer database-stored encrypted keys, then filesystem keys
    key_ref = resolve_project_ssh_key_reference(project)
    selected_ssh_key = None
    use_encrypted_key = False

    if key_ref and key_ref.key and key_ref.key.encrypted_private_key:
        # Use encrypted key from database via ssh-agent
        use_encrypted_key = True
        log.info(
            "Using encrypted SSH key from database for project %s (source: %s)",
            project.name,
            key_ref.source,
        )
    elif key_ref and key_ref.path:
        # Use filesystem key
        if _project_key_accessible_to_user(linux_username, key_ref.path):
            selected_ssh_key = key_ref.path
        else:
            log.warning(
                "Project SSH key at %s is not readable by user %s; falling back to user's own SSH config",
                key_ref.path,
                linux_username,
            )

    def _do_clone(env: dict[str, str] | None = None) -> Path:
        """Perform the git clone operation."""
        _git_clone_via_sudo(
            linux_username,
            project.repo_url,
            str(workspace_path),
            project.default_branch,
            env=env,
            ssh_key_path=selected_ssh_key,
        )
        log.info(
            "Initialized workspace for project %s, user %s at %s",
            getattr(project, "name", project.id),
            getattr(user, "email", user.id),
            workspace_path,
        )
        return workspace_path

    def _cleanup_on_failure() -> None:
        """Clean up partial clone directory on failure."""
        if test_path(linux_username, str(workspace_path)) and not test_path(
            linux_username, str(workspace_path / ".git")
        ):
            try:
                rm_rf(linux_username, str(workspace_path), timeout=10)
            except SudoError:
                log.warning(
                    "Failed to clean up workspace directory after clone failure"
                )

    # Clone repository using sudo as the target user. Prefer the project/tenant
    # SSH key so users can work with repos that rely on centrally managed access.
    try:
        if use_encrypted_key and key_ref and key_ref.key:
            # Create a temporary key file accessible to the target user
            with ssh_key_file_for_user(
                key_ref.key.encrypted_private_key, linux_username
            ) as temp_key_path:
                env = {
                    "GIT_SSH_COMMAND": f"ssh -i {temp_key_path} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
                }
                return _do_clone(env=env)
        else:
            return _do_clone()
    except WorkspaceError:
        _cleanup_on_failure()
        raise


def get_workspace_status(project, user) -> dict[str, Any]:
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

    # Try to check workspace existence directly, fall back to sudo if permission denied
    exists = False
    has_git = False
    error = None

    try:
        exists = workspace_path.exists()
        has_git = exists and (workspace_path / ".git").exists()
    except PermissionError:
        # Flask app doesn't have permission to access the workspace directory
        # Use sudo to check as the target user
        linux_username = resolve_linux_username(user)
        if linux_username:
            log.debug(
                "Using sudo to check workspace for %s at %s",
                linux_username,
                workspace_path,
            )
            exists = test_path(linux_username, str(workspace_path))
            has_git = exists and test_path(linux_username, str(workspace_path / ".git"))
        else:
            error = f"Cannot check workspace: no Linux username for user {getattr(user, 'email', 'unknown')}"

    return {
        "exists": exists,
        "path": str(workspace_path),
        "has_git": has_git,
        "error": error,
    }


__all__ = [
    "WorkspaceError",
    "get_workspace_path",
    "workspace_exists",
    "initialize_workspace",
    "get_workspace_status",
]
