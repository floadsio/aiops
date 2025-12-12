"""API v1 Slack integration endpoints.

Provides endpoints for:
- Managing Slack integrations (CRUD)
- Testing Slack connections
- Managing Slack user mappings
- Triggering manual Slack polls
"""

from __future__ import annotations

from typing import Any

from flask import current_app, jsonify, request
from sqlalchemy.orm.attributes import flag_modified

from ...extensions import db
from ...models import SlackUserMapping, Tenant, TenantIntegration, User
from ...services.api_auth import audit_api_request, require_api_auth
from ...services.slack_service import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TRIGGER_EMOJI,
    list_bot_channels,
    test_slack_connection,
)
from . import api_v1_bp


def _slack_integration_to_dict(integration: TenantIntegration) -> dict[str, Any]:
    """Convert Slack integration to dictionary (without sensitive data).

    Args:
        integration: TenantIntegration model

    Returns:
        dict: Integration data (token masked)
    """
    settings = integration.settings or {}
    return {
        "id": integration.id,
        "tenant_id": integration.tenant_id,
        "name": integration.name,
        "provider": integration.provider,
        "enabled": integration.enabled,
        "channels": settings.get("channels", []),
        "trigger_emoji": settings.get("trigger_emoji", DEFAULT_TRIGGER_EMOJI),
        "trigger_keyword": settings.get("trigger_keyword"),
        "default_project_id": settings.get("default_project_id"),
        "notify_on_status_change": settings.get("notify_on_status_change", True),
        "notify_on_close": settings.get("notify_on_close", True),
        "sync_comments": settings.get("sync_comments", False),
        "poll_interval_minutes": settings.get("poll_interval_minutes", DEFAULT_POLL_INTERVAL),
        "created_at": integration.created_at.isoformat() if integration.created_at else None,
        "updated_at": integration.updated_at.isoformat() if integration.updated_at else None,
    }


def _slack_mapping_to_dict(mapping: SlackUserMapping) -> dict[str, Any]:
    """Convert SlackUserMapping to dictionary.

    Args:
        mapping: SlackUserMapping model

    Returns:
        dict: Mapping data
    """
    return {
        "id": mapping.id,
        "tenant_id": mapping.tenant_id,
        "slack_user_id": mapping.slack_user_id,
        "slack_display_name": mapping.slack_display_name,
        "slack_email": mapping.slack_email,
        "aiops_user_id": mapping.aiops_user_id,
        "aiops_user_name": mapping.aiops_user.name if mapping.aiops_user else None,
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Slack Integration CRUD
# ---------------------------------------------------------------------------


@api_v1_bp.get("/tenants/<int:tenant_id>/slack")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_slack_integrations(tenant_id: int):
    """List all Slack integrations for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        200: List of Slack integrations
        404: Tenant not found
    """
    tenant = Tenant.query.get_or_404(tenant_id)
    integrations = TenantIntegration.query.filter_by(
        tenant_id=tenant.id, provider="slack"
    ).all()

    return jsonify({
        "integrations": [_slack_integration_to_dict(i) for i in integrations],
        "count": len(integrations),
    })


@api_v1_bp.get("/slack/integrations/<int:integration_id>")
@require_api_auth(scopes=["read"])
@audit_api_request
def get_slack_integration(integration_id: int):
    """Get a specific Slack integration.

    Args:
        integration_id: Integration ID

    Returns:
        200: Integration data
        404: Integration not found
    """
    integration = TenantIntegration.query.filter_by(
        id=integration_id, provider="slack"
    ).first_or_404()

    return jsonify({"integration": _slack_integration_to_dict(integration)})


@api_v1_bp.post("/tenants/<int:tenant_id>/slack")
@require_api_auth(scopes=["write"])
@audit_api_request
def create_slack_integration(tenant_id: int):
    """Create a new Slack integration for a tenant.

    Request body:
        name (str): Integration name (required)
        bot_token (str): Slack Bot OAuth token (xoxb-...) (required)
        channels (list[str]): Channel IDs to monitor (required)
        default_project_id (int): Project ID for created issues (required)
        trigger_emoji (str, optional): Emoji to trigger issue creation (default: ticket)
        notify_on_status_change (bool, optional): Post to thread on status change (default: true)
        notify_on_close (bool, optional): Post summary when closed (default: true)
        sync_comments (bool, optional): Sync comments to Slack thread (default: false)
        poll_interval_minutes (int, optional): Polling interval (default: 5)

    Returns:
        201: Created integration
        400: Invalid request
        404: Tenant not found
    """
    tenant = Tenant.query.get_or_404(tenant_id)
    data = request.get_json(silent=True) or {}

    # Required fields
    name = (data.get("name") or "").strip()
    bot_token = (data.get("bot_token") or "").strip()
    channels = data.get("channels", [])
    default_project_id = data.get("default_project_id")

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not bot_token:
        return jsonify({"error": "bot_token is required"}), 400
    if not bot_token.startswith("xoxb-"):
        return jsonify({"error": "bot_token must be a Bot OAuth token (starts with xoxb-)"}), 400
    # channels and default_project_id can be configured later via update

    # Test the connection first
    test_result = test_slack_connection(bot_token)
    if not test_result.get("ok"):
        return jsonify({
            "error": "Failed to connect to Slack",
            "details": test_result.get("error"),
        }), 400

    # Optional settings
    settings = {
        "channels": channels,
        "default_project_id": default_project_id,
        "trigger_emoji": data.get("trigger_emoji", DEFAULT_TRIGGER_EMOJI),
        "trigger_keyword": data.get("trigger_keyword"),  # e.g., "@aiops" or "!issue"
        "notify_on_status_change": data.get("notify_on_status_change", True),
        "notify_on_close": data.get("notify_on_close", True),
        "sync_comments": data.get("sync_comments", False),
        "poll_interval_minutes": data.get("poll_interval_minutes", DEFAULT_POLL_INTERVAL),
        "team_name": test_result.get("team"),
        "team_id": test_result.get("team_id"),
        "bot_user_id": test_result.get("bot_user_id"),
    }

    integration = TenantIntegration(
        tenant_id=tenant.id,
        provider="slack",
        name=name,
        api_token=bot_token,
        settings=settings,
        enabled=True,
    )

    db.session.add(integration)
    db.session.commit()

    return jsonify({
        "integration": _slack_integration_to_dict(integration),
        "message": f"Connected to Slack workspace: {test_result.get('team')}",
    }), 201


@api_v1_bp.put("/slack/integrations/<int:integration_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def update_slack_integration(integration_id: int):
    """Update a Slack integration.

    Request body (all optional):
        name (str): Integration name
        bot_token (str): New bot token (will test connection)
        channels (list[str]): Channel IDs to monitor
        default_project_id (int): Project ID for created issues
        trigger_emoji (str): Emoji to trigger issue creation
        notify_on_status_change (bool): Post to thread on status change
        notify_on_close (bool): Post summary when closed
        sync_comments (bool): Sync comments to Slack thread
        poll_interval_minutes (int): Polling interval
        enabled (bool): Enable/disable integration

    Returns:
        200: Updated integration
        400: Invalid request
        404: Integration not found
    """
    integration = TenantIntegration.query.filter_by(
        id=integration_id, provider="slack"
    ).first_or_404()

    data = request.get_json(silent=True) or {}
    settings = integration.settings or {}

    # Update name if provided
    if "name" in data:
        name = (data["name"] or "").strip()
        if name:
            integration.name = name

    # Update bot token if provided (test connection first)
    if "bot_token" in data:
        bot_token = (data["bot_token"] or "").strip()
        if bot_token:
            if not bot_token.startswith("xoxb-"):
                return jsonify({"error": "bot_token must start with xoxb-"}), 400
            test_result = test_slack_connection(bot_token)
            if not test_result.get("ok"):
                return jsonify({
                    "error": "Failed to connect with new token",
                    "details": test_result.get("error"),
                }), 400
            integration.api_token = bot_token
            settings["team_name"] = test_result.get("team")
            settings["team_id"] = test_result.get("team_id")
            settings["bot_user_id"] = test_result.get("bot_user_id")

    # Update settings
    if "channels" in data:
        settings["channels"] = data["channels"]
    if "default_project_id" in data:
        settings["default_project_id"] = data["default_project_id"]
    if "trigger_emoji" in data:
        settings["trigger_emoji"] = data["trigger_emoji"]
    if "trigger_keyword" in data:
        settings["trigger_keyword"] = data["trigger_keyword"]
    if "notify_on_status_change" in data:
        settings["notify_on_status_change"] = data["notify_on_status_change"]
    if "notify_on_close" in data:
        settings["notify_on_close"] = data["notify_on_close"]
    if "sync_comments" in data:
        settings["sync_comments"] = data["sync_comments"]
    if "poll_interval_minutes" in data:
        settings["poll_interval_minutes"] = data["poll_interval_minutes"]

    integration.settings = settings
    flag_modified(integration, "settings")

    # Update enabled status
    if "enabled" in data:
        integration.enabled = bool(data["enabled"])

    db.session.commit()

    return jsonify({"integration": _slack_integration_to_dict(integration)})


@api_v1_bp.delete("/slack/integrations/<int:integration_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def delete_slack_integration(integration_id: int):
    """Delete a Slack integration.

    Args:
        integration_id: Integration ID

    Returns:
        200: Deletion confirmed
        404: Integration not found
    """
    integration = TenantIntegration.query.filter_by(
        id=integration_id, provider="slack"
    ).first_or_404()

    name = integration.name
    db.session.delete(integration)
    db.session.commit()

    return jsonify({"message": f"Deleted Slack integration: {name}"})


# ---------------------------------------------------------------------------
# Slack Connection Testing
# ---------------------------------------------------------------------------


@api_v1_bp.post("/slack/test-connection")
@require_api_auth(scopes=["read"])
@audit_api_request
def test_slack_api_connection():
    """Test a Slack API connection with a bot token.

    Request body:
        bot_token (str): Slack Bot OAuth token to test

    Returns:
        200: Connection successful with workspace info
        400: Connection failed
    """
    data = request.get_json(silent=True) or {}
    bot_token = (data.get("bot_token") or "").strip()

    if not bot_token:
        return jsonify({"error": "bot_token is required"}), 400

    result = test_slack_connection(bot_token)

    if result.get("ok"):
        return jsonify({
            "ok": True,
            "team": result.get("team"),
            "team_id": result.get("team_id"),
            "bot_user": result.get("bot_user"),
        })
    else:
        return jsonify({
            "ok": False,
            "error": result.get("error"),
        }), 400


@api_v1_bp.get("/slack/integrations/<int:integration_id>/channels")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_slack_bot_channels(integration_id: int):
    """List channels the Slack bot has access to.

    Args:
        integration_id: Integration ID

    Returns:
        200: List of accessible channels
        404: Integration not found
    """
    integration = TenantIntegration.query.filter_by(
        id=integration_id, provider="slack"
    ).first_or_404()

    channels = list_bot_channels(integration.api_token)

    return jsonify({
        "channels": channels,
        "count": len(channels),
    })


# ---------------------------------------------------------------------------
# Slack User Mappings
# ---------------------------------------------------------------------------


@api_v1_bp.get("/tenants/<int:tenant_id>/slack/users")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_slack_user_mappings(tenant_id: int):
    """List all Slack user mappings for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        200: List of user mappings
        404: Tenant not found
    """
    tenant = Tenant.query.get_or_404(tenant_id)
    mappings = (
        SlackUserMapping.query.filter_by(tenant_id=tenant.id)
        .order_by(SlackUserMapping.slack_display_name)
        .all()
    )

    return jsonify({
        "mappings": [_slack_mapping_to_dict(m) for m in mappings],
        "count": len(mappings),
    })


@api_v1_bp.put("/slack/users/<int:mapping_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def update_slack_user_mapping(mapping_id: int):
    """Update a Slack user mapping (link/unlink aiops user).

    Request body:
        aiops_user_id (int|null): User ID to link, or null to unlink

    Returns:
        200: Updated mapping
        400: Invalid user ID
        404: Mapping not found
    """
    mapping = SlackUserMapping.query.get_or_404(mapping_id)
    data = request.get_json(silent=True) or {}

    aiops_user_id = data.get("aiops_user_id")

    if aiops_user_id is not None:
        user = User.query.get(aiops_user_id)
        if not user:
            return jsonify({"error": f"User {aiops_user_id} not found"}), 400
        mapping.aiops_user_id = aiops_user_id
    else:
        mapping.aiops_user_id = None

    db.session.commit()

    return jsonify({"mapping": _slack_mapping_to_dict(mapping)})


@api_v1_bp.delete("/slack/users/<int:mapping_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def delete_slack_user_mapping(mapping_id: int):
    """Delete a Slack user mapping.

    Args:
        mapping_id: Mapping ID

    Returns:
        200: Deletion confirmed
        404: Mapping not found
    """
    mapping = SlackUserMapping.query.get_or_404(mapping_id)
    display_name = mapping.slack_display_name

    db.session.delete(mapping)
    db.session.commit()

    return jsonify({"message": f"Deleted Slack user mapping: {display_name}"})


# ---------------------------------------------------------------------------
# Manual Polling
# ---------------------------------------------------------------------------


@api_v1_bp.post("/slack/poll")
@require_api_auth(scopes=["write"])
@audit_api_request
def trigger_slack_poll():
    """Manually trigger a Slack poll for all integrations.

    Returns:
        200: Poll triggered
    """
    from ...services.sync_scheduler import trigger_slack_poll_now

    trigger_slack_poll_now(current_app._get_current_object())

    return jsonify({"message": "Slack poll triggered"})


@api_v1_bp.post("/slack/integrations/<int:integration_id>/poll")
@require_api_auth(scopes=["write"])
@audit_api_request
def trigger_single_slack_poll(integration_id: int):
    """Manually trigger a Slack poll for a single integration.

    Args:
        integration_id: Integration ID

    Returns:
        200: Poll results
        404: Integration not found
    """
    from ...services.slack_service import get_slack_integrations, poll_integration

    # Verify integration exists (404 if not found)
    TenantIntegration.query.filter_by(
        id=integration_id, provider="slack"
    ).first_or_404()

    # Build config for this integration
    configs = get_slack_integrations()
    config = next((c for c in configs if c.integration_id == integration_id), None)

    if not config:
        return jsonify({"error": "Integration not properly configured"}), 400

    results = poll_integration(config)

    return jsonify({
        "processed": results["processed"],
        "errors": results["errors"],
    })
