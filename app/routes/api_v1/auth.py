"""API v1 authentication and API key management endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import g, jsonify, request

from ...extensions import db
from ...models import APIKey
from ...services.api_auth import audit_api_request, require_api_auth
from . import api_v1_bp


def _api_key_to_dict(api_key: APIKey, include_key: str | None = None) -> dict[str, Any]:
    """Convert APIKey model to dictionary.

    Args:
        api_key: The API key model
        include_key: If provided, include the full key in the response (only for newly created keys)

    Returns:
        dict: API key data
    """
    data = {
        "id": api_key.id,
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "scopes": api_key.scopes or [],
        "is_active": api_key.is_active,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
    }
    if include_key:
        data["key"] = include_key
    return data


@api_v1_bp.get("/auth/keys")
@require_api_auth()
@audit_api_request
def list_api_keys():
    """List all API keys for the current user.

    Returns:
        200: List of API keys (without sensitive data)
    """
    user = g.api_user
    keys = APIKey.query.filter_by(user_id=user.id).order_by(APIKey.created_at.desc()).all()
    return jsonify({"keys": [_api_key_to_dict(k) for k in keys]})


@api_v1_bp.post("/auth/keys")
@require_api_auth()
@audit_api_request
def create_api_key():
    """Create a new API key for the current user.

    Request body:
        name (str): Human-readable name for the key
        scopes (list[str]): List of scopes (e.g., ['read', 'write'])
        expires_days (int, optional): Days until expiration (default: no expiration)

    Returns:
        201: Created API key (includes full key - only shown once)
    """
    user = g.api_user
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Key name is required"}), 400

    scopes = data.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        return jsonify({"error": "At least one scope is required"}), 400

    # Validate scopes
    valid_scopes = {"read", "write", "admin"}
    for scope in scopes:
        if scope not in valid_scopes:
            return jsonify({"error": f"Invalid scope: {scope}. Valid scopes: {', '.join(valid_scopes)}"}), 400

    # Generate API key
    full_key, key_hash, key_prefix = APIKey.generate_key()

    # Calculate expiration if specified
    expires_at = None
    expires_days = data.get("expires_days")
    if isinstance(expires_days, int) and expires_days > 0:
        expires_at = datetime.utcnow() + timedelta(days=expires_days)

    # Create API key
    api_key = APIKey(
        user_id=user.id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=scopes,
        expires_at=expires_at,
    )
    db.session.add(api_key)
    db.session.commit()

    return jsonify({
        "key": _api_key_to_dict(api_key, include_key=full_key),
        "message": "API key created successfully. Save this key securely - it won't be shown again."
    }), 201


@api_v1_bp.patch("/auth/keys/<int:key_id>")
@require_api_auth()
@audit_api_request
def update_api_key(key_id: int):
    """Update an API key.

    Args:
        key_id: ID of the API key to update

    Request body:
        name (str, optional): New name for the key
        scopes (list[str], optional): New scopes
        is_active (bool, optional): Activate or deactivate the key

    Returns:
        200: Updated API key
        404: Key not found
    """
    user = g.api_user
    api_key = APIKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not api_key:
        return jsonify({"error": "API key not found"}), 404

    data = request.get_json(silent=True) or {}

    # Update name if provided
    name = data.get("name")
    if name and isinstance(name, str):
        api_key.name = name.strip()

    # Update scopes if provided
    scopes = data.get("scopes")
    if scopes is not None:
        if not isinstance(scopes, list) or not scopes:
            return jsonify({"error": "At least one scope is required"}), 400
        valid_scopes = {"read", "write", "admin"}
        for scope in scopes:
            if scope not in valid_scopes:
                return jsonify({"error": f"Invalid scope: {scope}"}), 400
        api_key.scopes = scopes

    # Update active status if provided
    is_active = data.get("is_active")
    if is_active is not None:
        api_key.is_active = bool(is_active)

    db.session.commit()
    return jsonify({"key": _api_key_to_dict(api_key)})


@api_v1_bp.delete("/auth/keys/<int:key_id>")
@require_api_auth()
@audit_api_request
def delete_api_key(key_id: int):
    """Delete an API key.

    Args:
        key_id: ID of the API key to delete

    Returns:
        204: Key deleted successfully
        404: Key not found
    """
    user = g.api_user
    api_key = APIKey.query.filter_by(id=key_id, user_id=user.id).first()
    if not api_key:
        return jsonify({"error": "API key not found"}), 404

    db.session.delete(api_key)
    db.session.commit()
    return ("", 204)


@api_v1_bp.get("/auth/me")
@require_api_auth()
@audit_api_request
def get_current_user():
    """Get current authenticated user information.

    Returns:
        200: User data including API key info if token auth was used
    """
    user = g.api_user
    api_key = g.api_key

    user_data = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
    }

    if api_key:
        user_data["auth_method"] = "api_key"
        user_data["api_key_id"] = api_key.id
        user_data["api_key_name"] = api_key.name
        user_data["scopes"] = api_key.scopes or []
    else:
        user_data["auth_method"] = "session"

    return jsonify({"user": user_data})
