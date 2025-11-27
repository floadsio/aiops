"""Activity logging service for tracking all aiops operations.

This service provides centralized activity logging for web UI and CLI operations.
It captures user actions, resource changes, and system events for audit and monitoring.
"""

from __future__ import annotations

from typing import Any, Optional

from flask import current_app, has_request_context, request
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import Activity


def log_activity(
    action_type: str,
    user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    resource_name: Optional[str] = None,
    status: str = "success",
    description: Optional[str] = None,
    extra_data: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
    source: str = "web",
) -> Optional[Activity]:
    """Log an activity event.

    Args:
        action_type: Type of action (e.g., 'issue.create', 'git.commit')
        user_id: ID of the user performing the action
        resource_type: Type of resource (e.g., 'issue', 'project')
        resource_id: ID of the resource
        resource_name: Human-readable resource name
        status: Status of the action ('success', 'failure', 'pending')
        description: Human-readable description
        extra_data: Additional context as JSON
        error_message: Error details if status='failure'
        source: Source of the action ('web' or 'cli')

    Returns:
        Activity: The created activity log entry, or None if logging failed
    """
    try:
        # Get IP address from request context if available
        ip_address = None
        if has_request_context() and request:
            ip_address = request.remote_addr

        # Create activity log entry
        activity = Activity(
            user_id=user_id,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            status=status,
            description=description,
            extra_data=extra_data,
            error_message=error_message,
            ip_address=ip_address,
            source=source,
        )

        db.session.add(activity)
        db.session.commit()

        return activity

    except SQLAlchemyError as e:
        # Don't let activity logging failures break the application
        if current_app:
            current_app.logger.error(f"Failed to log activity: {e}")
        db.session.rollback()
        return None


def get_recent_activities(
    limit: int = 50,
    user_id: Optional[int] = None,
    action_type: Optional[str] = None,
    resource_type: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
) -> list[Activity]:
    """Get recent activity log entries with optional filters.

    Args:
        limit: Maximum number of activities to return
        user_id: Filter by user ID
        action_type: Filter by action type
        resource_type: Filter by resource type
        status: Filter by status
        source: Filter by source ('web' or 'cli')

    Returns:
        List of Activity records
    """
    query = Activity.query

    # Apply filters
    if user_id is not None:
        query = query.filter(Activity.user_id == user_id)
    if action_type:
        query = query.filter(Activity.action_type == action_type)
    if resource_type:
        query = query.filter(Activity.resource_type == resource_type)
    if status:
        query = query.filter(Activity.status == status)
    if source:
        query = query.filter(Activity.source == source)

    # Order by most recent first
    query = query.order_by(Activity.created_at.desc())

    # Apply limit
    query = query.limit(limit)

    return query.all()


def get_user_activities(user_id: int, limit: int = 50) -> list[Activity]:
    """Get recent activities for a specific user.

    Args:
        user_id: ID of the user
        limit: Maximum number of activities to return

    Returns:
        List of Activity records for the user
    """
    return get_recent_activities(limit=limit, user_id=user_id)


def get_resource_activities(
    resource_type: str, resource_id: int, limit: int = 50
) -> list[Activity]:
    """Get recent activities for a specific resource.

    Args:
        resource_type: Type of resource (e.g., 'issue', 'project')
        resource_id: ID of the resource
        limit: Maximum number of activities to return

    Returns:
        List of Activity records for the resource
    """
    return (
        Activity.query.filter(
            Activity.resource_type == resource_type, Activity.resource_id == resource_id
        )
        .order_by(Activity.created_at.desc())
        .limit(limit)
        .all()
    )


# Activity type constants for consistency
class ActivityType:
    """Standard activity types for aiops operations."""

    # Issue operations
    ISSUE_CREATE = "issue.create"
    ISSUE_UPDATE = "issue.update"
    ISSUE_CLOSE = "issue.close"
    ISSUE_REOPEN = "issue.reopen"
    ISSUE_COMMENT = "issue.comment"
    ISSUE_ASSIGN = "issue.assign"
    ISSUE_SYNC = "issue.sync"

    # Git operations
    GIT_CLONE = "git.clone"
    GIT_PULL = "git.pull"
    GIT_PUSH = "git.push"
    GIT_COMMIT = "git.commit"
    GIT_BRANCH_CREATE = "git.branch.create"
    GIT_BRANCH_DELETE = "git.branch.delete"
    GIT_CHECKOUT = "git.checkout"
    GIT_PR_CREATE = "git.pr.create"
    GIT_PR_MERGE = "git.pr.merge"

    # Session operations
    SESSION_START = "session.start"
    SESSION_ATTACH = "session.attach"
    SESSION_KILL = "session.kill"
    SESSION_RESPAWN = "session.respawn"

    # Project operations
    PROJECT_CREATE = "project.create"
    PROJECT_UPDATE = "project.update"
    PROJECT_DELETE = "project.delete"

    # Tenant operations
    TENANT_CREATE = "tenant.create"
    TENANT_UPDATE = "tenant.update"
    TENANT_DELETE = "tenant.delete"

    # User operations
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"

    # System operations
    SYSTEM_BACKUP = "system.backup"
    SYSTEM_RESTORE = "system.restore"
    SYSTEM_UPDATE = "system.update"
    SYSTEM_RESTART = "system.restart"

    # Integration operations
    INTEGRATION_CREATE = "integration.create"
    INTEGRATION_UPDATE = "integration.update"
    INTEGRATION_DELETE = "integration.delete"
    INTEGRATION_TEST = "integration.test"


# Resource type constants
class ResourceType:
    """Standard resource types for aiops."""

    ISSUE = "issue"
    PROJECT = "project"
    TENANT = "tenant"
    USER = "user"
    SESSION = "session"
    INTEGRATION = "integration"
    SSH_KEY = "ssh_key"
    BACKUP = "backup"
