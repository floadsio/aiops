"""Unified git service using CLI tools (gh/glab) with PAT authentication.

This service routes git operations to the appropriate CLI tool based on the
project's integration provider (GitHub or GitLab).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..models import Project
from . import gh_service, glab_service

log = logging.getLogger(__name__)


class CliGitServiceError(Exception):
    """Base exception for CLI git service errors."""


def _get_provider(project: Project) -> Optional[str]:
    """Determine which provider (github/gitlab) the project uses.

    Returns:
        'github', 'gitlab', or None if no integration
    """
    integration = getattr(project, "integration", None)
    if not integration:
        return None

    return getattr(integration, "provider", None)


def clone_repo(
    project: Project,
    target_path: Path,
    *,
    branch: Optional[str] = None,
) -> None:
    """Clone a repository using the appropriate CLI tool.

    Args:
        project: Project to clone
        target_path: Local path to clone into
        branch: Optional branch to checkout

    Raises:
        CliGitServiceError: If clone fails or provider not supported
    """
    provider = _get_provider(project)

    if provider == "github":
        try:
            gh_service.clone_repo(project, target_path, branch=branch)
        except gh_service.GhServiceError as exc:
            raise CliGitServiceError(f"GitHub clone failed: {exc}") from exc
    elif provider == "gitlab":
        try:
            glab_service.clone_repo(project, target_path, branch=branch)
        except glab_service.GlabServiceError as exc:
            raise CliGitServiceError(f"GitLab clone failed: {exc}") from exc
    else:
        raise CliGitServiceError(
            f"Project {project.id} provider '{provider}' not supported for CLI git operations"
        )


def pull_repo(project: Project, repo_path: Path) -> str:
    """Pull latest changes from repository.

    Args:
        project: Project to pull
        repo_path: Local repository path

    Returns:
        Output message from pull operation

    Raises:
        CliGitServiceError: If pull fails or provider not supported
    """
    provider = _get_provider(project)

    if provider == "github":
        try:
            return gh_service.pull_repo(project, repo_path)
        except gh_service.GhServiceError as exc:
            raise CliGitServiceError(f"GitHub pull failed: {exc}") from exc
    elif provider == "gitlab":
        try:
            return glab_service.pull_repo(project, repo_path)
        except glab_service.GlabServiceError as exc:
            raise CliGitServiceError(f"GitLab pull failed: {exc}") from exc
    else:
        raise CliGitServiceError(
            f"Project {project.id} provider '{provider}' not supported for CLI git operations"
        )


def push_repo(project: Project, repo_path: Path, branch: Optional[str] = None) -> str:
    """Push changes to repository.

    Args:
        project: Project to push
        repo_path: Local repository path
        branch: Branch to push (defaults to current branch)

    Returns:
        Output message from push operation

    Raises:
        CliGitServiceError: If push fails or provider not supported
    """
    provider = _get_provider(project)

    if provider == "github":
        try:
            return gh_service.push_repo(project, repo_path, branch=branch)
        except gh_service.GhServiceError as exc:
            raise CliGitServiceError(f"GitHub push failed: {exc}") from exc
    elif provider == "gitlab":
        try:
            return glab_service.push_repo(project, repo_path, branch=branch)
        except glab_service.GlabServiceError as exc:
            raise CliGitServiceError(f"GitLab push failed: {exc}") from exc
    else:
        raise CliGitServiceError(
            f"Project {project.id} provider '{provider}' not supported for CLI git operations"
        )


def get_repo_status(project: Project, repo_path: Path) -> dict[str, Any]:
    """Get repository status.

    Args:
        project: Project to check
        repo_path: Local repository path

    Returns:
        Dictionary with status information

    Raises:
        CliGitServiceError: If status check fails or provider not supported
    """
    provider = _get_provider(project)

    if provider == "github":
        try:
            return gh_service.get_repo_status(project, repo_path)
        except gh_service.GhServiceError as exc:
            raise CliGitServiceError(f"GitHub status failed: {exc}") from exc
    elif provider == "gitlab":
        try:
            return glab_service.get_repo_status(project, repo_path)
        except glab_service.GlabServiceError as exc:
            raise CliGitServiceError(f"GitLab status failed: {exc}") from exc
    else:
        raise CliGitServiceError(
            f"Project {project.id} provider '{provider}' not supported for CLI git operations"
        )


def supports_cli_git(project: Project) -> bool:
    """Check if a project supports CLI-based git operations.

    Returns:
        True if project has GitHub or GitLab integration with access token
    """
    provider = _get_provider(project)
    if provider not in ("github", "gitlab"):
        return False

    integration = getattr(project, "integration", None)
    if not integration:
        return False

    token = getattr(integration, "access_token", None)
    return bool(token)
