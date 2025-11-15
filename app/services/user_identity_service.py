"""Service layer for managing user identity mappings across issue providers.

This module provides functions to create, update, retrieve, and validate
user identity mappings for GitHub, GitLab, and Jira.
"""

from __future__ import annotations

from typing import Optional

from flask import current_app

from ..extensions import db
from ..models import User, UserIdentityMap


class UserIdentityError(Exception):
    """Raised when user identity operations fail."""


def get_or_create_identity_map(user_id: int) -> UserIdentityMap:
    """Get or create a UserIdentityMap for the specified user.

    Args:
        user_id: The aiops user ID

    Returns:
        UserIdentityMap instance

    Raises:
        UserIdentityError: If the user doesn't exist
    """
    user = User.query.get(user_id)
    if user is None:
        raise UserIdentityError(f"User with ID {user_id} not found.")

    identity_map = UserIdentityMap.query.filter_by(user_id=user_id).first()
    if identity_map is None:
        identity_map = UserIdentityMap(user_id=user_id)
        db.session.add(identity_map)
        db.session.flush()

    return identity_map


def get_identity_map(user_id: int) -> Optional[UserIdentityMap]:
    """Get the UserIdentityMap for the specified user.

    Args:
        user_id: The aiops user ID

    Returns:
        UserIdentityMap instance or None if not found
    """
    return UserIdentityMap.query.filter_by(user_id=user_id).first()


def update_identity_map(
    user_id: int,
    *,
    github_username: Optional[str] = None,
    gitlab_username: Optional[str] = None,
    jira_account_id: Optional[str] = None,
) -> UserIdentityMap:
    """Update identity mappings for a user.

    Args:
        user_id: The aiops user ID
        github_username: GitHub username (optional)
        gitlab_username: GitLab username (optional)
        jira_account_id: Jira account ID (optional)

    Returns:
        Updated UserIdentityMap instance

    Raises:
        UserIdentityError: If the user doesn't exist
    """
    identity_map = get_or_create_identity_map(user_id)

    if github_username is not None:
        identity_map.github_username = github_username.strip() or None

    if gitlab_username is not None:
        identity_map.gitlab_username = gitlab_username.strip() or None

    if jira_account_id is not None:
        identity_map.jira_account_id = jira_account_id.strip() or None

    db.session.flush()
    current_app.logger.info(
        f"Updated identity map for user_id={user_id}: "
        f"github={identity_map.github_username}, "
        f"gitlab={identity_map.gitlab_username}, "
        f"jira={identity_map.jira_account_id}"
    )

    return identity_map


def delete_identity_map(user_id: int) -> bool:
    """Delete the identity map for a user.

    Args:
        user_id: The aiops user ID

    Returns:
        True if deleted, False if not found
    """
    identity_map = UserIdentityMap.query.filter_by(user_id=user_id).first()
    if identity_map is None:
        return False

    db.session.delete(identity_map)
    db.session.flush()
    return True


def resolve_github_username(user_id: int) -> Optional[str]:
    """Resolve GitHub username for an aiops user.

    Args:
        user_id: The aiops user ID

    Returns:
        GitHub username or None if not mapped
    """
    identity_map = get_identity_map(user_id)
    return identity_map.github_username if identity_map else None


def resolve_gitlab_username(user_id: int) -> Optional[str]:
    """Resolve GitLab username for an aiops user.

    Args:
        user_id: The aiops user ID

    Returns:
        GitLab username or None if not mapped
    """
    identity_map = get_identity_map(user_id)
    return identity_map.gitlab_username if identity_map else None


def resolve_jira_account_id(user_id: int) -> Optional[str]:
    """Resolve Jira account ID for an aiops user.

    Args:
        user_id: The aiops user ID

    Returns:
        Jira account ID or None if not mapped
    """
    identity_map = get_identity_map(user_id)
    return identity_map.jira_account_id if identity_map else None
