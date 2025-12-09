"""Notification service for managing user notifications.

Provides CRUD operations for notifications and notification preferences,
as well as utilities for querying and bulk operations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from flask import current_app

from ..extensions import db
from ..models import Notification, NotificationPreferences, User


# Notification type constants
class NotificationType:
    """Constants for notification types."""

    # Issue-related
    ISSUE_ASSIGNED = "issue.assigned"
    ISSUE_MENTIONED = "issue.mentioned"
    ISSUE_COMMENTED = "issue.commented"
    ISSUE_STATUS_CHANGED = "issue.status_changed"
    ISSUE_CREATED = "issue.created"

    # Project-related
    PROJECT_UPDATED = "project.updated"
    PROJECT_SYNC_ERROR = "project.sync_error"

    # System-related (admin only)
    SYSTEM_BACKUP_COMPLETED = "system.backup_completed"
    SYSTEM_BACKUP_FAILED = "system.backup_failed"
    SYSTEM_UPDATE_AVAILABLE = "system.update_available"
    SYSTEM_INTEGRATION_ERROR = "system.integration_error"

    # AI Session-related
    SESSION_COMPLETED = "session.completed"
    SESSION_ERROR = "session.error"

    # All types grouped by category
    ISSUE_TYPES = [
        ISSUE_ASSIGNED,
        ISSUE_MENTIONED,
        ISSUE_COMMENTED,
        ISSUE_STATUS_CHANGED,
        ISSUE_CREATED,
    ]
    PROJECT_TYPES = [PROJECT_UPDATED, PROJECT_SYNC_ERROR]
    SYSTEM_TYPES = [
        SYSTEM_BACKUP_COMPLETED,
        SYSTEM_BACKUP_FAILED,
        SYSTEM_UPDATE_AVAILABLE,
        SYSTEM_INTEGRATION_ERROR,
    ]
    SESSION_TYPES = [SESSION_COMPLETED, SESSION_ERROR]
    ALL_TYPES = ISSUE_TYPES + PROJECT_TYPES + SYSTEM_TYPES + SESSION_TYPES


class NotificationPriority:
    """Constants for notification priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


def create_notification(
    user_id: int,
    notification_type: str,
    title: str,
    message: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    resource_url: Optional[str] = None,
    priority: str = NotificationPriority.NORMAL,
    metadata: Optional[dict] = None,
    expires_at: Optional[datetime] = None,
) -> Optional[Notification]:
    """Create a new notification for a user.

    Args:
        user_id: The user ID to notify
        notification_type: Type of notification (use NotificationType constants)
        title: Short title for the notification
        message: Optional longer message/description
        resource_type: Type of resource (e.g., 'issue', 'project', 'backup')
        resource_id: ID of the related resource
        resource_url: URL to navigate to the resource
        priority: Priority level (use NotificationPriority constants)
        metadata: Additional metadata as a dictionary
        expires_at: Optional expiration datetime

    Returns:
        The created Notification object, or None if user preferences block it
    """
    # Check if notifications are enabled globally
    if not current_app.config.get("NOTIFICATIONS_ENABLED", True):
        return None

    # Check user preferences
    prefs = get_or_create_preferences(user_id)
    if notification_type not in prefs.enabled_types:
        return None

    # Check if project is muted
    if metadata and "project_id" in metadata:
        if metadata["project_id"] in prefs.muted_projects:
            return None

    # Check if integration is muted
    if metadata and "integration_id" in metadata:
        if metadata["integration_id"] in prefs.muted_integrations:
            return None

    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_url=resource_url,
        priority=priority,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
    )

    if metadata:
        notification.set_metadata(metadata)

    db.session.add(notification)
    db.session.commit()

    return notification


def get_user_notifications(
    user_id: int,
    unread_only: bool = False,
    notification_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    """Get notifications for a user with optional filtering.

    Args:
        user_id: The user ID
        unread_only: If True, only return unread notifications
        notification_type: Filter by notification type
        limit: Maximum number of results (default 50)
        offset: Pagination offset

    Returns:
        List of Notification objects ordered by created_at descending
    """
    query = Notification.query.filter(Notification.user_id == user_id)

    if unread_only:
        query = query.filter(Notification.is_read == False)  # noqa: E712

    if notification_type:
        query = query.filter(Notification.notification_type == notification_type)

    # Exclude expired notifications
    now = datetime.utcnow()
    query = query.filter(
        db.or_(Notification.expires_at.is_(None), Notification.expires_at > now)
    )

    return (
        query.order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_unread_count(user_id: int) -> int:
    """Get the count of unread notifications for a user.

    Args:
        user_id: The user ID

    Returns:
        Number of unread notifications
    """
    now = datetime.utcnow()
    return (
        Notification.query.filter(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
            db.or_(Notification.expires_at.is_(None), Notification.expires_at > now),
        ).count()
    )


def mark_as_read(notification_id: int, user_id: int) -> bool:
    """Mark a notification as read.

    Args:
        notification_id: The notification ID
        user_id: The user ID (for authorization)

    Returns:
        True if successful, False if notification not found or unauthorized
    """
    notification = Notification.query.filter(
        Notification.id == notification_id, Notification.user_id == user_id
    ).first()

    if not notification:
        return False

    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.session.commit()
    return True


def mark_as_unread(notification_id: int, user_id: int) -> bool:
    """Mark a notification as unread.

    Args:
        notification_id: The notification ID
        user_id: The user ID (for authorization)

    Returns:
        True if successful, False if notification not found or unauthorized
    """
    notification = Notification.query.filter(
        Notification.id == notification_id, Notification.user_id == user_id
    ).first()

    if not notification:
        return False

    notification.is_read = False
    notification.read_at = None
    db.session.commit()
    return True


def mark_all_as_read(user_id: int) -> int:
    """Mark all notifications for a user as read.

    Args:
        user_id: The user ID

    Returns:
        Number of notifications marked as read
    """
    now = datetime.utcnow()
    count = (
        Notification.query.filter(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
        .update({"is_read": True, "read_at": now})
    )
    db.session.commit()
    return count


def delete_notification(notification_id: int, user_id: int) -> bool:
    """Delete a notification.

    Args:
        notification_id: The notification ID
        user_id: The user ID (for authorization)

    Returns:
        True if successful, False if notification not found or unauthorized
    """
    notification = Notification.query.filter(
        Notification.id == notification_id, Notification.user_id == user_id
    ).first()

    if not notification:
        return False

    db.session.delete(notification)
    db.session.commit()
    return True


def cleanup_expired_notifications() -> int:
    """Delete expired notifications.

    Also deletes notifications older than the retention period (default 60 days).

    Returns:
        Number of notifications deleted
    """
    retention_days = current_app.config.get("NOTIFICATIONS_RETENTION_DAYS", 60)
    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
    now = datetime.utcnow()

    count = Notification.query.filter(
        db.or_(
            db.and_(
                Notification.expires_at.isnot(None), Notification.expires_at < now
            ),
            Notification.created_at < cutoff_date,
        )
    ).delete(synchronize_session=False)

    db.session.commit()
    return count


def get_or_create_preferences(user_id: int) -> NotificationPreferences:
    """Get or create notification preferences for a user.

    Args:
        user_id: The user ID

    Returns:
        NotificationPreferences object
    """
    prefs = NotificationPreferences.query.filter_by(user_id=user_id).first()
    if not prefs:
        prefs = NotificationPreferences.create_default(user_id)
        db.session.add(prefs)
        db.session.commit()
    return prefs


def update_preferences(
    user_id: int,
    enabled_types: Optional[list[str]] = None,
    muted_projects: Optional[list[int]] = None,
    muted_integrations: Optional[list[int]] = None,
    email_notifications: Optional[bool] = None,
    email_frequency: Optional[str] = None,
) -> NotificationPreferences:
    """Update notification preferences for a user.

    Args:
        user_id: The user ID
        enabled_types: List of enabled notification types
        muted_projects: List of muted project IDs
        muted_integrations: List of muted integration IDs
        email_notifications: Whether to enable email notifications
        email_frequency: Email notification frequency

    Returns:
        Updated NotificationPreferences object
    """
    prefs = get_or_create_preferences(user_id)

    if enabled_types is not None:
        prefs.enabled_types = enabled_types
    if muted_projects is not None:
        prefs.muted_projects = muted_projects
    if muted_integrations is not None:
        prefs.muted_integrations = muted_integrations
    if email_notifications is not None:
        prefs.email_notifications = email_notifications
    if email_frequency is not None:
        prefs.email_frequency = email_frequency

    db.session.commit()
    return prefs


def get_notification_by_id(notification_id: int, user_id: int) -> Optional[Notification]:
    """Get a single notification by ID (with user authorization).

    Args:
        notification_id: The notification ID
        user_id: The user ID (for authorization)

    Returns:
        Notification object or None
    """
    return Notification.query.filter(
        Notification.id == notification_id, Notification.user_id == user_id
    ).first()


def notify_admins(
    notification_type: str,
    title: str,
    message: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    resource_url: Optional[str] = None,
    priority: str = NotificationPriority.NORMAL,
    metadata: Optional[dict] = None,
) -> list[Notification]:
    """Send a notification to all admin users.

    Args:
        Same as create_notification, but without user_id

    Returns:
        List of created Notification objects
    """
    admins = User.query.filter_by(is_admin=True).all()
    notifications = []

    for admin in admins:
        notification = create_notification(
            user_id=admin.id,
            notification_type=notification_type,
            title=title,
            message=message,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_url=resource_url,
            priority=priority,
            metadata=metadata,
        )
        if notification:
            notifications.append(notification)

    return notifications
