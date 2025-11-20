"""Activity logging decorator for API endpoints.

This module provides decorators and utilities for automatically logging
activities from API requests (CLI operations).
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Optional

from flask import g, request

from .activity_service import ActivityType, ResourceType, log_activity


def log_api_activity(
    action_type: str,
    resource_type: Optional[str] = None,
    get_resource_id: Optional[Callable[[Any], Optional[int]]] = None,
    get_resource_name: Optional[Callable[[Any], Optional[str]]] = None,
    get_description: Optional[Callable[[Any], Optional[str]]] = None,
):
    """Decorator to automatically log API endpoint activities.

    Args:
        action_type: Activity type constant (e.g., ActivityType.ISSUE_CREATE)
        resource_type: Resource type constant (e.g., ResourceType.ISSUE)
        get_resource_id: Function to extract resource ID from response data
        get_resource_name: Function to extract resource name from response data
        get_description: Function to generate description from response data

    Example:
        @api_bp.post("/projects")
        @log_api_activity(
            action_type=ActivityType.PROJECT_CREATE,
            resource_type=ResourceType.PROJECT,
            get_resource_id=lambda data: data.get("project", {}).get("id"),
            get_resource_name=lambda data: data.get("project", {}).get("name"),
            get_description=lambda data: f"Created project: {data.get('project', {}).get('name')}"
        )
        def create_project():
            # ... endpoint logic
            return jsonify({"project": project_dict}), 201
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Execute the endpoint
            response = func(*args, **kwargs)

            # Extract response data and status code
            if isinstance(response, tuple):
                response_data, status_code = response[0], response[1]
            else:
                response_data = response
                status_code = 200

            # Only log successful operations (2xx status codes)
            if 200 <= status_code < 300:
                try:
                    # Get user ID from g.api_user (set in before_request)
                    user_id = None
                    if hasattr(g, "api_user") and g.api_user:
                        user_id = g.api_user.id

                    # Extract response JSON data
                    response_json = (
                        response_data.get_json()
                        if hasattr(response_data, "get_json")
                        else {}
                    )

                    # Extract resource information
                    resource_id = (
                        get_resource_id(response_json) if get_resource_id else None
                    )
                    resource_name = (
                        get_resource_name(response_json) if get_resource_name else None
                    )
                    description = (
                        get_description(response_json) if get_description else None
                    )

                    # Determine source (CLI vs web)
                    # API requests from CLI typically have User-Agent containing 'python' or 'requests'
                    user_agent = request.headers.get("User-Agent", "").lower()
                    source = "cli" if any(
                        x in user_agent for x in ["python", "requests", "curl", "httpx"]
                    ) else "web"

                    # Log the activity
                    log_activity(
                        action_type=action_type,
                        user_id=user_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        resource_name=resource_name,
                        status="success",
                        description=description,
                        source=source,
                    )

                except Exception as e:
                    # Don't fail the request if activity logging fails
                    # Just log the error
                    import logging

                    logging.getLogger(__name__).warning(
                        f"Failed to log activity for {action_type}: {e}"
                    )

            return response

        return wrapper

    return decorator


def log_git_operation(
    operation: str,
    get_project_id: Optional[Callable[[Any], Optional[int]]] = None,
    get_project_name: Optional[Callable[[Any], Optional[str]]] = None,
):
    """Decorator specifically for git operations.

    Args:
        operation: Git operation name (e.g., 'commit', 'push', 'pull')
        get_project_id: Function to extract project ID
        get_project_name: Function to extract project name
    """
    # Map operation to activity type
    action_type_map = {
        "commit": ActivityType.GIT_COMMIT,
        "push": ActivityType.GIT_PUSH,
        "pull": ActivityType.GIT_PULL,
        "checkout": ActivityType.GIT_CHECKOUT,
        "branch": ActivityType.GIT_BRANCH_CREATE,
        "clone": ActivityType.GIT_CLONE,
    }

    action_type = action_type_map.get(operation, f"git.{operation}")

    return log_api_activity(
        action_type=action_type,
        resource_type=ResourceType.PROJECT,
        get_resource_id=get_project_id,
        get_resource_name=get_project_name,
        get_description=lambda data: f"Git {operation}: {get_project_name(data) if get_project_name else 'project'}",
    )


def log_session_operation(
    operation: str,
    get_project_id: Optional[Callable[[Any], Optional[int]]] = None,
    get_project_name: Optional[Callable[[Any], Optional[str]]] = None,
):
    """Decorator specifically for session operations.

    Args:
        operation: Session operation name (e.g., 'start', 'attach', 'kill')
        get_project_id: Function to extract project ID
        get_project_name: Function to extract project name
    """
    # Map operation to activity type
    action_type_map = {
        "start": ActivityType.SESSION_START,
        "attach": ActivityType.SESSION_ATTACH,
        "kill": ActivityType.SESSION_KILL,
        "respawn": ActivityType.SESSION_RESPAWN,
    }

    action_type = action_type_map.get(operation, f"session.{operation}")

    return log_api_activity(
        action_type=action_type,
        resource_type=ResourceType.PROJECT,
        get_resource_id=get_project_id,
        get_resource_name=get_project_name,
        get_description=lambda data: f"Session {operation}: {get_project_name(data) if get_project_name else 'project'}",
    )
