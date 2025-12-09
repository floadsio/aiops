"""Notification generator for creating notifications from system events.

Hooks into issue sync, comment sync, and other system events to generate
notifications for users based on their preferences.
"""

from __future__ import annotations

import re
from typing import Optional


from ..models import ExternalIssue, User, UserIdentityMap
from .notification_service import (
    NotificationPriority,
    NotificationType,
    create_notification,
    notify_admins,
)


def resolve_user_from_external_identity(
    external_username: str, provider: str, integration_id: Optional[int] = None
) -> Optional[User]:
    """Resolve an external username to a local user via UserIdentityMap.

    Args:
        external_username: The external username (e.g., GitHub username, Jira account ID)
        provider: The provider name ('github', 'gitlab', 'jira')
        integration_id: Optional integration ID for more specific matching

    Returns:
        User object if mapping exists, None otherwise
    """
    query = UserIdentityMap.query.filter_by(
        external_username=external_username, provider=provider
    )

    if integration_id:
        query = query.filter_by(integration_id=integration_id)

    mapping = query.first()
    if mapping:
        return User.query.get(mapping.user_id)
    return None


def notify_issue_assigned(issue: ExternalIssue, assignee_username: str) -> bool:
    """Generate notification when an issue is assigned to a user.

    Args:
        issue: The ExternalIssue object
        assignee_username: The external username of the assignee

    Returns:
        True if notification was created, False otherwise
    """
    if not assignee_username:
        return False

    # Get provider from integration
    integration = issue.project_integration.integration
    provider = integration.provider.lower() if integration else None
    if not provider:
        return False

    # Resolve external username to local user
    user = resolve_user_from_external_identity(
        assignee_username, provider, integration.id
    )
    if not user:
        return False

    # Get project info for metadata
    project = issue.project_integration.project
    project_name = project.name if project else "Unknown"

    notification = create_notification(
        user_id=user.id,
        notification_type=NotificationType.ISSUE_ASSIGNED,
        title=f"Issue assigned: {issue.external_id}",
        message=issue.title,
        resource_type="issue",
        resource_id=issue.id,
        resource_url=f"/admin/issues?highlight={issue.id}",
        priority=NotificationPriority.NORMAL,
        metadata={
            "project_id": project.id if project else None,
            "project_name": project_name,
            "issue_external_id": issue.external_id,
            "provider": provider,
            "integration_id": integration.id,
        },
    )

    return notification is not None


def notify_issue_commented(
    issue: ExternalIssue,
    comment_author: str,
    comment_body: str,
    comment_id: Optional[str] = None,
) -> list[User]:
    """Generate notifications when a new comment is added to an issue.

    Notifies:
    - The issue assignee
    - Users mentioned in the comment (@username)

    Args:
        issue: The ExternalIssue object
        comment_author: External username of comment author
        comment_body: The comment text
        comment_id: Optional external comment ID

    Returns:
        List of users who were notified
    """
    notified_users: list[User] = []

    # Get provider from integration
    integration = issue.project_integration.integration
    provider = integration.provider.lower() if integration else None
    if not provider:
        return notified_users

    # Get project info
    project = issue.project_integration.project
    project_name = project.name if project else "Unknown"

    # Don't notify the comment author
    author_user = resolve_user_from_external_identity(
        comment_author, provider, integration.id
    )
    author_user_id = author_user.id if author_user else None

    # Build metadata
    base_metadata = {
        "project_id": project.id if project else None,
        "project_name": project_name,
        "issue_external_id": issue.external_id,
        "provider": provider,
        "integration_id": integration.id,
        "comment_author": comment_author,
    }

    # Notify issue assignee (if not the comment author)
    if issue.assignee:
        assignee_user = resolve_user_from_external_identity(
            issue.assignee, provider, integration.id
        )
        if assignee_user and assignee_user.id != author_user_id:
            notification = create_notification(
                user_id=assignee_user.id,
                notification_type=NotificationType.ISSUE_COMMENTED,
                title=f"New comment on {issue.external_id}",
                message=_truncate_message(comment_body, 200),
                resource_type="issue",
                resource_id=issue.id,
                resource_url=f"/admin/issues?highlight={issue.id}",
                metadata=base_metadata,
            )
            if notification:
                notified_users.append(assignee_user)

    # Find and notify mentioned users
    mentioned_users = _extract_mentions(comment_body, provider, integration.id)
    for mentioned_user in mentioned_users:
        if mentioned_user.id != author_user_id and mentioned_user not in notified_users:
            notification = create_notification(
                user_id=mentioned_user.id,
                notification_type=NotificationType.ISSUE_MENTIONED,
                title=f"You were mentioned in {issue.external_id}",
                message=_truncate_message(comment_body, 200),
                resource_type="issue",
                resource_id=issue.id,
                resource_url=f"/admin/issues?highlight={issue.id}",
                priority=NotificationPriority.HIGH,
                metadata=base_metadata,
            )
            if notification:
                notified_users.append(mentioned_user)

    return notified_users


def notify_issue_status_changed(
    issue: ExternalIssue, old_status: str, new_status: str
) -> bool:
    """Generate notification when an issue status changes.

    Notifies the issue assignee.

    Args:
        issue: The ExternalIssue object
        old_status: Previous status
        new_status: New status

    Returns:
        True if notification was created, False otherwise
    """
    if not issue.assignee:
        return False

    # Get provider from integration
    integration = issue.project_integration.integration
    provider = integration.provider.lower() if integration else None
    if not provider:
        return False

    # Resolve assignee
    user = resolve_user_from_external_identity(
        issue.assignee, provider, integration.id
    )
    if not user:
        return False

    # Get project info
    project = issue.project_integration.project
    project_name = project.name if project else "Unknown"

    notification = create_notification(
        user_id=user.id,
        notification_type=NotificationType.ISSUE_STATUS_CHANGED,
        title=f"Issue {issue.external_id} status changed",
        message=f"{old_status} → {new_status}",
        resource_type="issue",
        resource_id=issue.id,
        resource_url=f"/admin/issues?highlight={issue.id}",
        metadata={
            "project_id": project.id if project else None,
            "project_name": project_name,
            "issue_external_id": issue.external_id,
            "provider": provider,
            "integration_id": integration.id,
            "old_status": old_status,
            "new_status": new_status,
        },
    )

    return notification is not None


def notify_sync_error(
    project_id: int,
    project_name: str,
    integration_id: int,
    provider: str,
    error_message: str,
) -> list:
    """Notify admins about a sync error.

    Args:
        project_id: Project ID
        project_name: Project name
        integration_id: Integration ID
        provider: Provider name
        error_message: Error details

    Returns:
        List of created notifications
    """
    return notify_admins(
        notification_type=NotificationType.PROJECT_SYNC_ERROR,
        title=f"Sync failed for {project_name}",
        message=_truncate_message(error_message, 500),
        resource_type="project",
        resource_id=project_id,
        resource_url=f"/projects/{project_id}",
        priority=NotificationPriority.HIGH,
        metadata={
            "project_id": project_id,
            "project_name": project_name,
            "integration_id": integration_id,
            "provider": provider,
        },
    )


def notify_backup_completed(backup_id: int, description: str) -> list:
    """Notify admins about a successful backup.

    Args:
        backup_id: Backup ID
        description: Backup description

    Returns:
        List of created notifications
    """
    return notify_admins(
        notification_type=NotificationType.SYSTEM_BACKUP_COMPLETED,
        title="Backup completed successfully",
        message=description,
        resource_type="backup",
        resource_id=backup_id,
        resource_url="/admin/settings",
        priority=NotificationPriority.LOW,
        metadata={"backup_id": backup_id},
    )


def notify_backup_failed(error_message: str) -> list:
    """Notify admins about a failed backup.

    Args:
        error_message: Error details

    Returns:
        List of created notifications
    """
    return notify_admins(
        notification_type=NotificationType.SYSTEM_BACKUP_FAILED,
        title="Backup failed",
        message=_truncate_message(error_message, 500),
        resource_type="backup",
        resource_url="/admin/settings",
        priority=NotificationPriority.CRITICAL,
    )


def notify_integration_error(
    integration_id: int,
    integration_name: str,
    provider: str,
    error_message: str,
) -> list:
    """Notify admins about an integration error.

    Args:
        integration_id: Integration ID
        integration_name: Integration name
        provider: Provider name
        error_message: Error details

    Returns:
        List of created notifications
    """
    return notify_admins(
        notification_type=NotificationType.SYSTEM_INTEGRATION_ERROR,
        title=f"Integration error: {integration_name}",
        message=_truncate_message(error_message, 500),
        resource_type="integration",
        resource_id=integration_id,
        resource_url="/admin/settings",
        priority=NotificationPriority.HIGH,
        metadata={
            "integration_id": integration_id,
            "integration_name": integration_name,
            "provider": provider,
        },
    )


def notify_session_completed(
    user_id: int,
    session_id: str,
    project_name: str,
    tool: str,
    duration_minutes: Optional[int] = None,
) -> Optional:
    """Notify user when their AI session completes.

    Args:
        user_id: User ID
        session_id: Session ID
        project_name: Project name
        tool: Tool used (claude, codex, shell)
        duration_minutes: Session duration

    Returns:
        Created notification or None
    """
    message = f"Session in {project_name} finished"
    if duration_minutes:
        message += f" after {duration_minutes} minutes"

    return create_notification(
        user_id=user_id,
        notification_type=NotificationType.SESSION_COMPLETED,
        title=f"AI session completed ({tool})",
        message=message,
        resource_type="session",
        resource_url=f"/projects/{project_name}",
        priority=NotificationPriority.LOW,
        metadata={
            "session_id": session_id,
            "project_name": project_name,
            "tool": tool,
            "duration_minutes": duration_minutes,
        },
    )


def notify_session_error(
    user_id: int,
    session_id: str,
    project_name: str,
    tool: str,
    error_message: str,
) -> Optional:
    """Notify user when their AI session encounters an error.

    Args:
        user_id: User ID
        session_id: Session ID
        project_name: Project name
        tool: Tool used (claude, codex, shell)
        error_message: Error details

    Returns:
        Created notification or None
    """
    return create_notification(
        user_id=user_id,
        notification_type=NotificationType.SESSION_ERROR,
        title=f"AI session error ({tool})",
        message=_truncate_message(error_message, 300),
        resource_type="session",
        resource_url=f"/projects/{project_name}",
        priority=NotificationPriority.HIGH,
        metadata={
            "session_id": session_id,
            "project_name": project_name,
            "tool": tool,
        },
    )


def _extract_mentions(
    text: str, provider: str, integration_id: Optional[int] = None
) -> list[User]:
    """Extract @mentions from text and resolve to users.

    Args:
        text: Text containing @mentions
        provider: Provider name for username resolution
        integration_id: Optional integration ID

    Returns:
        List of resolved User objects
    """
    users: list[User] = []

    if not text:
        return users

    # Different mention patterns for different providers
    if provider == "jira":
        # Jira uses [~accountid:xxx] format
        patterns = [
            r"\[~accountid:([^\]]+)\]",  # Account ID format
            r"\[~([^\]]+)\]",  # Username format
        ]
    else:
        # GitHub/GitLab use @username
        patterns = [r"@([a-zA-Z0-9_-]+)"]

    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            user = resolve_user_from_external_identity(match, provider, integration_id)
            if user and user not in users:
                users.append(user)

    return users


def _truncate_message(text: str, max_length: int) -> str:
    """Truncate text to a maximum length with ellipsis.

    Args:
        text: Text to truncate
        max_length: Maximum length

    Returns:
        Truncated text
    """
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
