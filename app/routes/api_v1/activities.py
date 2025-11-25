"""AIops REST API v1 - Activities endpoints.

This module provides endpoints for querying activity logs.
"""

from __future__ import annotations

from flask import jsonify, request

from . import api_v1_bp


@api_v1_bp.get("/activities")
def list_activities_api():
    """List activities via API (for CLI)."""
    from ...models import Activity
    from ...services.activity_service import get_recent_activities

    # Get filter parameters
    limit_str = request.args.get("limit", "50")
    try:
        limit = min(int(limit_str), 1000)
    except ValueError:
        limit = 50

    user_id_str = request.args.get("user_id")
    user_id = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
        except ValueError:
            pass

    action_type = request.args.get("action_type") or None
    resource_type = request.args.get("resource_type") or None
    status = request.args.get("status") or None
    source = request.args.get("source") or None

    # Fetch activities
    activities = get_recent_activities(
        limit=limit,
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        status=status,
        source=source,
    )

    # Convert to JSON
    activity_list = []
    for activity in activities:
        activity_dict = {
            "id": activity.id,
            "timestamp": activity.created_at.isoformat() if activity.created_at else None,
            "user_id": activity.user_id,
            "user_email": activity.user.email if activity.user else None,
            "action_type": activity.action_type,
            "resource_type": activity.resource_type,
            "resource_id": activity.resource_id,
            "resource_name": activity.resource_name,
            "status": activity.status,
            "description": activity.description,
            "extra_data": activity.extra_data,
            "error_message": activity.error_message,
            "ip_address": activity.ip_address,
            "source": activity.source,
        }
        activity_list.append(activity_dict)

    return jsonify({"count": len(activity_list), "activities": activity_list})
