"""Notifications API endpoints.

Provides REST API for managing user notifications and preferences.
"""

from flask import g, request

from ...services.api_auth import require_api_auth
from ...services.notification_service import (
    NotificationType,
    delete_notification,
    get_notification_by_id,
    get_or_create_preferences,
    get_unread_count,
    get_user_notifications,
    mark_all_as_read,
    mark_as_read,
    mark_as_unread,
    update_preferences,
)
from . import api_v1_bp


@api_v1_bp.get("/notifications")
@require_api_auth(scopes=["read"])
def list_notifications():
    """List notifications for the authenticated user.

    Query parameters:
        unread_only: Filter to unread notifications only (default: false)
        type: Filter by notification type
        limit: Maximum number of results (default: 50, max: 100)
        offset: Pagination offset (default: 0)

    Returns:
        JSON object with notifications list and metadata
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    # Parse query parameters
    unread_only = request.args.get("unread_only", "false").lower() == "true"
    notification_type = request.args.get("type")
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))

    notifications = get_user_notifications(
        user_id=user.id,
        unread_only=unread_only,
        notification_type=notification_type,
        limit=limit,
        offset=offset,
    )

    unread_count = get_unread_count(user.id)

    return {
        "notifications": [n.to_dict() for n in notifications],
        "unread_count": unread_count,
        "limit": limit,
        "offset": offset,
    }


@api_v1_bp.get("/notifications/unread-count")
@require_api_auth(scopes=["read"])
def get_notifications_unread_count():
    """Get the count of unread notifications.

    Returns:
        JSON object with count
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    count = get_unread_count(user.id)
    return {"count": count}


@api_v1_bp.get("/notifications/<int:notification_id>")
@require_api_auth(scopes=["read"])
def get_notification(notification_id: int):
    """Get a specific notification.

    Args:
        notification_id: The notification ID

    Returns:
        JSON notification object
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    notification = get_notification_by_id(notification_id, user.id)
    if not notification:
        return {"error": "Notification not found"}, 404

    return notification.to_dict()


@api_v1_bp.post("/notifications/<int:notification_id>/read")
@require_api_auth(scopes=["write"])
def mark_notification_read(notification_id: int):
    """Mark a notification as read.

    Args:
        notification_id: The notification ID

    Returns:
        JSON success response
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    success = mark_as_read(notification_id, user.id)
    if not success:
        return {"error": "Notification not found"}, 404

    return {"success": True}


@api_v1_bp.post("/notifications/<int:notification_id>/unread")
@require_api_auth(scopes=["write"])
def mark_notification_unread(notification_id: int):
    """Mark a notification as unread.

    Args:
        notification_id: The notification ID

    Returns:
        JSON success response
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    success = mark_as_unread(notification_id, user.id)
    if not success:
        return {"error": "Notification not found"}, 404

    return {"success": True}


@api_v1_bp.post("/notifications/mark-all-read")
@require_api_auth(scopes=["write"])
def mark_all_notifications_read():
    """Mark all notifications as read.

    Returns:
        JSON response with count of marked notifications
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    count = mark_all_as_read(user.id)
    return {"success": True, "count": count}


@api_v1_bp.delete("/notifications/<int:notification_id>")
@require_api_auth(scopes=["write"])
def delete_notification_endpoint(notification_id: int):
    """Delete a notification.

    Args:
        notification_id: The notification ID

    Returns:
        JSON success response
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    success = delete_notification(notification_id, user.id)
    if not success:
        return {"error": "Notification not found"}, 404

    return {"success": True}


@api_v1_bp.get("/notifications/preferences")
@require_api_auth(scopes=["read"])
def get_notification_preferences():
    """Get notification preferences for the authenticated user.

    Returns:
        JSON preferences object
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    prefs = get_or_create_preferences(user.id)
    return prefs.to_dict()


@api_v1_bp.put("/notifications/preferences")
@require_api_auth(scopes=["write"])
def update_notification_preferences():
    """Update notification preferences.

    Request body:
        enabled_types: List of enabled notification type strings
        muted_projects: List of muted project IDs
        muted_integrations: List of muted integration IDs
        email_notifications: Boolean for email notifications
        email_frequency: String for email frequency

    Returns:
        JSON updated preferences object
    """
    user = g.current_user or g.api_user
    if not user:
        return {"error": "Unauthorized"}, 401

    data = request.get_json() or {}

    prefs = update_preferences(
        user_id=user.id,
        enabled_types=data.get("enabled_types"),
        muted_projects=data.get("muted_projects"),
        muted_integrations=data.get("muted_integrations"),
        email_notifications=data.get("email_notifications"),
        email_frequency=data.get("email_frequency"),
    )

    return prefs.to_dict()


@api_v1_bp.get("/notifications/types")
@require_api_auth(scopes=["read"])
def get_notification_types():
    """Get available notification types.

    Returns:
        JSON object with notification types grouped by category
    """
    return {
        "types": {
            "issue": NotificationType.ISSUE_TYPES,
            "project": NotificationType.PROJECT_TYPES,
            "system": NotificationType.SYSTEM_TYPES,
            "session": NotificationType.SESSION_TYPES,
        },
        "all": NotificationType.ALL_TYPES,
    }
