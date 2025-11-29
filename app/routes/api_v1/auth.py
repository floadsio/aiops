"""API v1 authentication and API key management endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import current_app, g, jsonify, request

from ...extensions import db
from ...models import APIKey, TenantIntegration, UserIntegrationCredential
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


@api_v1_bp.get("/auth/integration-credentials")
@require_api_auth()
@audit_api_request
def list_user_credentials():
    """List all personal integration credentials for the current user.

    Returns:
        200: List of user credentials with integration details
    """
    user = g.api_user
    credentials = UserIntegrationCredential.query.filter_by(user_id=user.id).all()

    result = []
    for cred in credentials:
        # Handle case where integration may have been deleted
        integration = cred.integration
        if not integration:
            # Skip credentials for deleted integrations
            continue

        result.append({
            "id": cred.id,
            "integration_id": cred.integration_id,
            "integration_name": integration.name,
            "integration_provider": integration.provider,
            "has_settings": bool(cred.settings),
            "created_at": cred.created_at.isoformat() if cred.created_at else None,
            "updated_at": cred.updated_at.isoformat() if cred.updated_at else None,
        })

    return jsonify({"credentials": result})


@api_v1_bp.post("/auth/integration-credentials")
@require_api_auth()
@audit_api_request
def create_user_credential():
    """Set or update personal integration credentials for the current user.

    Request body:
        integration_id (int): Integration ID
        api_token (str): Personal API token/PAT for the integration
        settings (dict, optional): Additional provider-specific settings

    Returns:
        201: Credential created successfully
        400: Invalid request
        404: Integration not found
    """
    user = g.api_user
    data = request.get_json(silent=True) or {}

    integration_id = data.get("integration_id")
    api_token = (data.get("api_token") or "").strip()
    settings = data.get("settings")

    if not integration_id:
        return jsonify({"error": "integration_id is required"}), 400
    if not api_token:
        return jsonify({"error": "api_token is required"}), 400

    # Verify integration exists
    integration = TenantIntegration.query.get(integration_id)
    if not integration:
        return jsonify({"error": "Integration not found"}), 404

    # Check if credential already exists
    existing = UserIntegrationCredential.query.filter_by(
        user_id=user.id, integration_id=integration_id
    ).first()

    if existing:
        # Update existing
        existing.api_token = api_token
        if settings is not None:
            existing.settings = settings
        db.session.commit()
        return jsonify({
            "message": "Credential updated successfully",
            "credential_id": existing.id
        })
    else:
        # Create new
        credential = UserIntegrationCredential(
            user_id=user.id,
            integration_id=integration_id,
            api_token=api_token,
            settings=settings,
        )
        db.session.add(credential)
        db.session.commit()
        return jsonify({
            "message": "Credential created successfully",
            "credential_id": credential.id
        }), 201


@api_v1_bp.delete("/auth/integration-credentials/<int:credential_id>")
@require_api_auth()
@audit_api_request
def delete_user_credential(credential_id: int):
    """Delete a personal integration credential.

    Args:
        credential_id: ID of the credential to delete

    Returns:
        204: Credential deleted successfully
        404: Credential not found
    """
    user = g.api_user
    credential = UserIntegrationCredential.query.filter_by(
        id=credential_id, user_id=user.id
    ).first()

    if not credential:
        return jsonify({"error": "Credential not found"}), 404

    db.session.delete(credential)
    db.session.commit()
    return ("", 204)


@api_v1_bp.post("/auth/yadm/init")
@require_api_auth()
@audit_api_request
def initialize_yadm():
    """Initialize yadm for the current user's home directory.

    Clones the organization's dotfiles repository and sets up yadm.

    Request body:
        user_email (optional): Email of user to initialize for (current user if not provided)

    Returns:
        200: Yadm initialized successfully
        400: Bad request or initialization failed
        401: Unauthorized
    """
    from ...models import User, Project, Tenant
    from ...services.yadm_service import initialize_yadm_for_user, YadmServiceError

    user = g.api_user
    data = request.get_json() or {}

    try:
        # Optionally allow specifying a different user (for admin operations)
        target_user_email = data.get("user_email", user.email)
        if target_user_email != user.email and not user.is_admin:
            return jsonify({
                "error": "Only admins can initialize yadm for other users"
            }), 403

        # Get the target user
        target_user = User.query.filter_by(email=target_user_email).first()
        if not target_user:
            return jsonify({"error": f"User '{target_user_email}' not found"}), 404

        # Find dotfiles project for the user's tenant
        # Look across all tenants the user has projects in
        user_projects = Project.query.filter_by(owner_id=target_user.id).all()
        if not user_projects:
            return jsonify({
                "error": "User has no associated projects"
            }), 400

        # Try to find a dotfiles project in any of the user's tenants
        dotfiles_project = None
        for proj in user_projects:
            dotfiles = Project.query.filter_by(
                name="dotfiles", tenant_id=proj.tenant_id
            ).first()
            if dotfiles:
                dotfiles_project = dotfiles
                break

        if not dotfiles_project:
            tenant_ids = [p.tenant_id for p in user_projects]
            return jsonify({
                "error": f"No dotfiles project found in any of user's tenants: {tenant_ids}"
            }), 400

        # Initialize yadm for the user
        result = initialize_yadm_for_user(
            target_user,
            repo_url=dotfiles_project.repo_url,
            repo_branch=dotfiles_project.default_branch or "main"
        )

        return jsonify(result), 200

    except YadmServiceError as exc:
        return jsonify({
            "error": str(exc),
            "status": "failed"
        }), 400
    except Exception as exc:
        return jsonify({
            "error": f"Unexpected error: {exc}",
            "status": "failed"
        }), 500


@api_v1_bp.post("/dotfiles/init")
@require_api_auth()
@audit_api_request
def dotfiles_init():
    """Initialize dotfiles for current user.

    Uses personal config override if set, otherwise uses global config.

    Returns:
        200: Dotfiles initialized successfully
        400: Bad request or initialization failed
    """
    from ...services.yadm_service import initialize_yadm_for_user, YadmServiceError

    user = g.api_user
    repo_url = user.personal_dotfile_repo_url or current_app.config.get("DOTFILE_REPO_URL")
    repo_branch = user.personal_dotfile_branch or current_app.config.get("DOTFILE_REPO_BRANCH", "main")

    if not repo_url:
        return jsonify({
            "error": "No dotfiles repository configured"
        }), 400

    try:
        result = initialize_yadm_for_user(user, repo_url, repo_branch)
        return jsonify(result), 200
    except YadmServiceError as exc:
        return jsonify({
            "error": str(exc),
            "status": "failed"
        }), 400


@api_v1_bp.post("/dotfiles/pull-and-update")
@require_api_auth()
@audit_api_request
def dotfiles_pull_and_update():
    """Pull latest changes and re-run bootstrap.

    Returns:
        200: Update completed successfully
        400: Update failed
    """
    from ...services.yadm_service import pull_and_apply_yadm_update, YadmServiceError

    user = g.api_user
    linux_username = user.email.split("@")[0]
    user_home = f"/home/{linux_username}"

    try:
        result = pull_and_apply_yadm_update(linux_username, user_home)
        return jsonify(result), 200
    except YadmServiceError as exc:
        return jsonify({
            "error": str(exc),
            "status": "failed"
        }), 400


@api_v1_bp.post("/dotfiles/decrypt")
@require_api_auth()
@audit_api_request
def dotfiles_decrypt():
    """Decrypt encrypted dotfiles.

    Returns:
        200: Decrypt completed
        400: Decrypt failed
    """
    from ...services.yadm_service import yadm_decrypt, YadmServiceError

    user = g.api_user
    linux_username = user.email.split("@")[0]
    user_home = f"/home/{linux_username}"

    try:
        yadm_decrypt(linux_username, user_home)
        return jsonify({
            "status": "success",
            "message": "Encrypted files decrypted successfully"
        }), 200
    except YadmServiceError as exc:
        return jsonify({
            "error": str(exc),
            "status": "failed"
        }), 400


@api_v1_bp.get("/dotfiles/status")
@require_api_auth()
@audit_api_request
def dotfiles_status():
    """Get current yadm status snapshot.

    Returns:
        200: Status retrieved successfully
        400: Failed to get status
    """
    from ...services.yadm_service import get_full_yadm_status

    user = g.api_user

    try:
        status = get_full_yadm_status(user)
        return jsonify(status), 200
    except Exception as exc:
        return jsonify({
            "error": str(exc),
            "status": "error"
        }), 400


@api_v1_bp.get("/dotfiles/files")
@require_api_auth()
@audit_api_request
def dotfiles_files():
    """Get cached yadm files with optional filtering by category or search pattern.

    Query parameters:
        category: Filter by category (ssh_keys, kubeconfigs, git_configs, etc.)
        search: Glob pattern to search files (e.g., "*.config", ".ssh/*")

    Returns:
        200: Files retrieved successfully
        400: Invalid parameters
        404: No cache available
    """
    from ...services.yadm_service import (
        get_cached_yadm_files,
        find_yadm_files_by_category,
        search_yadm_files,
        FILE_CATEGORIES,
    )

    category = request.args.get("category")
    search_pattern = request.args.get("search")

    try:
        # If category filter is specified
        if category:
            if category not in FILE_CATEGORIES and category != "other":
                return jsonify({
                    "error": f"Invalid category. Valid categories: {list(FILE_CATEGORIES.keys()) + ['other']}"
                }), 400

            files = find_yadm_files_by_category(category)
            return jsonify({
                "files": files,
                "category": category,
                "total": len(files)
            }), 200

        # If search pattern is specified
        if search_pattern:
            files = search_yadm_files(search_pattern)
            return jsonify({
                "files": files,
                "search": search_pattern,
                "total": len(files)
            }), 200

        # Return full cache
        cache = get_cached_yadm_files()
        if not cache:
            return jsonify({
                "error": "No cache available. Run decrypt or pull to populate."
            }), 404

        return jsonify({
            "tracked_files": cache.get("tracked_files", []),
            "archive_files": cache.get("archive_files", []),
            "categories": cache.get("categories", {}),
            "cached_at": cache.get("cached_at"),
            "total_tracked": cache.get("total_tracked", 0),
            "total_archive": cache.get("total_archive", 0)
        }), 200

    except Exception as exc:
        return jsonify({
            "error": str(exc),
            "status": "error"
        }), 400
