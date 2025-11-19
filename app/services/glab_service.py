"""GitLab CLI (glab) integration service.

This service handles git operations for GitLab repositories using the official
glab CLI tool with PAT authentication.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from flask import current_app

from ..models import Integration, Project

log = logging.getLogger(__name__)


class GlabServiceError(Exception):
    """Base exception for GitLab CLI service errors."""


@dataclass
class GlabContext:
    """Context for running glab commands with authentication."""

    repo_path: Path
    token: str
    repo_url: str


def _get_project_integration(project: Project) -> Optional[Integration]:
    """Get the GitLab integration for a project.

    Returns:
        The Integration model if project uses GitLab, None otherwise
    """
    # Check if project has an integration
    integration = getattr(project, "integration", None)
    if not integration:
        return None

    # Verify it's a GitLab integration
    provider = getattr(integration, "provider", None)
    if provider != "gitlab":
        return None

    return integration


def _run_glab_command(
    ctx: GlabContext,
    args: list[str],
    *,
    timeout: float = 60.0,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a glab command with PAT authentication.

    Args:
        ctx: GitLab context with authentication
        args: Command arguments (without 'glab' prefix)
        timeout: Command timeout in seconds
        check: Whether to raise on non-zero exit code

    Returns:
        CompletedProcess result

    Raises:
        GlabServiceError: If command fails
    """
    env = {
        **subprocess.os.environ.copy(),
        "GITLAB_TOKEN": ctx.token,
    }

    command = ["glab", *args]

    try:
        result = subprocess.run(
            command,
            cwd=ctx.repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
        return result
    except subprocess.TimeoutExpired as exc:
        raise GlabServiceError(f"Command timed out after {timeout}s: {' '.join(command)}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise GlabServiceError(
            f"glab command failed (exit {exc.returncode}): {stderr.strip()}"
        ) from exc
    except OSError as exc:
        raise GlabServiceError(f"Failed to execute glab command: {exc}") from exc


def clone_repo(
    project: Project,
    target_path: Path,
    *,
    branch: Optional[str] = None,
) -> None:
    """Clone a GitLab repository using glab CLI.

    Args:
        project: Project to clone
        target_path: Local path to clone into
        branch: Optional branch to checkout (defaults to project.default_branch)

    Raises:
        GlabServiceError: If clone fails
    """
    integration = _get_project_integration(project)
    if not integration:
        raise GlabServiceError(f"Project {project.id} does not have a GitLab integration")

    token = getattr(integration, "access_token", None)
    if not token:
        raise GlabServiceError(f"GitLab integration {integration.id} has no access token")

    # Create parent directory
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Extract group/project from URL
    # e.g., https://gitlab.com/group/project.git -> group/project
    repo_url = project.repo_url
    if repo_url.endswith(".git"):
        repo_url = repo_url[:-4]

    # Handle both gitlab.com and self-hosted GitLab instances
    if "gitlab.com/" in repo_url:
        repo_full_name = repo_url.split("gitlab.com/")[-1]
    else:
        # For self-hosted, extract domain and path
        parts = repo_url.split("://")[-1].split("/", 1)
        if len(parts) == 2:
            repo_full_name = parts[1]
        else:
            raise GlabServiceError(f"Cannot parse GitLab URL: {repo_url}")

    # Use glab repo clone
    env = {
        **subprocess.os.environ.copy(),
        "GITLAB_TOKEN": token,
    }

    clone_args = ["repo", "clone", repo_full_name, str(target_path)]
    if branch:
        clone_args.extend(["--", "-b", branch])
    elif project.default_branch:
        clone_args.extend(["--", "-b", project.default_branch])

    try:
        subprocess.run(
            ["glab", *clone_args],
            env=env,
            capture_output=True,
            text=True,
            timeout=300.0,
            check=True,
        )
        log.info(f"Cloned {repo_full_name} to {target_path}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise GlabServiceError(f"Failed to clone repository: {stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GlabServiceError("Repository clone timed out after 300s") from exc


def pull_repo(project: Project, repo_path: Path) -> str:
    """Pull latest changes from GitLab repository.

    Args:
        project: Project to pull
        repo_path: Local repository path

    Returns:
        Output message from pull operation

    Raises:
        GlabServiceError: If pull fails
    """
    integration = _get_project_integration(project)
    if not integration:
        raise GlabServiceError(f"Project {project.id} does not have a GitLab integration")

    token = getattr(integration, "access_token", None)
    if not token:
        raise GlabServiceError(f"GitLab integration {integration.id} has no access token")

    env = {
        **subprocess.os.environ.copy(),
        "GITLAB_TOKEN": token,
    }

    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=300.0,
            check=True,
        )
        output = result.stdout.strip() or "Pull completed"
        log.info(f"Pulled {project.repo_url}: {output}")
        return output
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise GlabServiceError(f"Failed to pull repository: {stderr.strip()}") from exc


def push_repo(project: Project, repo_path: Path, branch: Optional[str] = None) -> str:
    """Push changes to GitLab repository.

    Args:
        project: Project to push
        repo_path: Local repository path
        branch: Branch to push (defaults to current branch)

    Returns:
        Output message from push operation

    Raises:
        GlabServiceError: If push fails
    """
    integration = _get_project_integration(project)
    if not integration:
        raise GlabServiceError(f"Project {project.id} does not have a GitLab integration")

    token = getattr(integration, "access_token", None)
    if not token:
        raise GlabServiceError(f"GitLab integration {integration.id} has no access token")

    env = {
        **subprocess.os.environ.copy(),
        "GITLAB_TOKEN": token,
    }

    push_args = ["git", "push"]
    if branch:
        push_args.extend(["origin", branch])

    try:
        result = subprocess.run(
            push_args,
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=300.0,
            check=True,
        )
        output = result.stdout.strip() or result.stderr.strip() or "Push completed"
        log.info(f"Pushed {project.repo_url}: {output}")
        return output
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise GlabServiceError(f"Failed to push repository: {stderr.strip()}") from exc


def get_repo_status(project: Project, repo_path: Path) -> dict[str, Any]:
    """Get repository status using git commands with GitLab authentication.

    Args:
        project: Project to check
        repo_path: Local repository path

    Returns:
        Dictionary with status information

    Raises:
        GlabServiceError: If status check fails
    """
    integration = _get_project_integration(project)
    if not integration:
        raise GlabServiceError(f"Project {project.id} does not have a GitLab integration")

    token = getattr(integration, "access_token", None)
    if not token:
        raise GlabServiceError(f"GitLab integration {integration.id} has no access token")

    env = {
        **subprocess.os.environ.copy(),
        "GITLAB_TOKEN": token,
    }

    try:
        # Get branch name
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )
        branch = branch_result.stdout.strip()

        # Get status
        status_result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )
        status = status_result.stdout.strip()

        # Check if dirty
        dirty_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )
        dirty = bool(dirty_result.stdout.strip())

        return {
            "branch": branch,
            "status_summary": status,
            "dirty": dirty,
            "workspace_path": str(repo_path),
        }
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise GlabServiceError(f"Failed to get repository status: {stderr.strip()}") from exc
