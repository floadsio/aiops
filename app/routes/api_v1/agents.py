"""API v1 agent context management endpoints."""

from __future__ import annotations

from datetime import datetime

from flask import jsonify, request

from ...extensions import db
from ...models import GlobalAgentContext
from ...services.api_auth import audit_api_request, require_api_auth
from ...services import global_agents_service
from . import api_v1_bp


@api_v1_bp.route("/agents/global", methods=["GET"])
@require_api_auth(scopes=["read"])
@audit_api_request
def get_global_agent_context():
    """Get the global agent context.

    Returns the global AGENTS.md content that is prepended to all
    AGENTS.override.md files. If no global context is set in the database,
    returns null to indicate the system will fall back to AGENTS.md from
    the repository.

    Returns:
        JSON response with global context content and metadata
    """
    global_context = GlobalAgentContext.query.order_by(
        GlobalAgentContext.updated_at.desc()
    ).first()

    if not global_context:
        return jsonify(
            {
                "content": None,
                "updated_at": None,
                "updated_by": None,
                "message": "No global context set. System will use AGENTS.md from repository.",
            }
        )

    return jsonify(
        {
            "id": global_context.id,
            "content": global_context.content,
            "created_at": global_context.created_at.isoformat(),
            "updated_at": global_context.updated_at.isoformat(),
            "updated_by": (
                {
                    "id": global_context.updated_by.id,
                    "name": global_context.updated_by.name,
                    "email": global_context.updated_by.email,
                }
                if global_context.updated_by
                else None
            ),
        }
    )


@api_v1_bp.route("/agents/global", methods=["PUT"])
@require_api_auth(scopes=["write", "admin"])
@audit_api_request
def update_global_agent_context():
    """Update or create the global agent context with automatic versioning.

    Request body:
        {
            "content": "Global AGENTS.md content",
            "description": "Optional change description"  # optional
        }

    Returns:
        JSON response with updated global context
    """
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field in request body"}), 400

    content = data["content"]
    if not isinstance(content, str):
        return jsonify({"error": "'content' must be a string"}), 400

    # Strip whitespace but keep content structure
    content = content.strip()
    if not content:
        return jsonify({"error": "'content' cannot be empty"}), 400

    # Get optional description
    description = data.get("description")

    # Get current user from API auth context
    from flask import g

    user_id = getattr(g, "api_user_id", None)

    try:
        # Use versioning service to update (auto-saves version before updating)
        global_context = global_agents_service.update_global_context_with_versioning(
            content, user_id, description
        )

        return jsonify(
            {
                "id": global_context.id,
                "content": global_context.content,
                "created_at": global_context.created_at.isoformat(),
                "updated_at": global_context.updated_at.isoformat(),
                "updated_by": (
                    {
                        "id": global_context.updated_by.id,
                        "name": global_context.updated_by.name,
                        "email": global_context.updated_by.email,
                    }
                    if global_context.updated_by
                    else None
                ),
                "message": "Global agent context updated successfully (version saved)",
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@api_v1_bp.route("/agents/global", methods=["DELETE"])
@require_api_auth(scopes=["write", "admin"])
@audit_api_request
def delete_global_agent_context():
    """Delete the global agent context.

    This will cause the system to fall back to reading AGENTS.md from
    the repository for all future AGENTS.override.md file generations.

    Returns:
        JSON response confirming deletion
    """
    global_context = GlobalAgentContext.query.order_by(
        GlobalAgentContext.updated_at.desc()
    ).first()

    if not global_context:
        return jsonify(
            {
                "message": "No global context to delete. System already uses AGENTS.md from repository."
            }
        )

    db.session.delete(global_context)
    db.session.commit()

    return jsonify(
        {
            "message": "Global agent context deleted. System will now use AGENTS.md from repository."
        }
    )


# Version history endpoints


@api_v1_bp.route("/agents/global/history", methods=["GET"])
@require_api_auth(scopes=["read"])
@audit_api_request
def get_global_agents_history():
    """Get version history for global agents context.

    Query parameters:
        limit: Maximum number of versions to return (default: 50, max: 200)
        offset: Number of versions to skip (default: 0)

    Returns:
        JSON response with list of versions and metadata
    """
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    versions = global_agents_service.get_version_history(limit, offset)
    total_count = global_agents_service.get_version_count()

    return jsonify(
        {
            "versions": [
                {
                    "id": v.id,
                    "version_number": v.version_number,
                    "change_description": v.change_description,
                    "created_at": v.created_at.isoformat(),
                    "created_by": (
                        {
                            "id": v.created_by.id,
                            "name": v.created_by.name,
                            "email": v.created_by.email,
                        }
                        if v.created_by
                        else None
                    ),
                    "content_length": len(v.content),
                }
                for v in versions
            ],
            "total": total_count,
            "limit": limit,
            "offset": offset,
        }
    )


@api_v1_bp.route("/agents/global/history/<int:version_number>", methods=["GET"])
@require_api_auth(scopes=["read"])
@audit_api_request
def get_global_agents_version(version_number: int):
    """Get a specific version of global agents context.

    Args:
        version_number: The version number to retrieve

    Returns:
        JSON response with version details including full content
    """
    version = global_agents_service.get_version_by_number(version_number)

    if not version:
        return jsonify({"error": f"Version {version_number} not found"}), 404

    return jsonify(
        {
            "id": version.id,
            "version_number": version.version_number,
            "content": version.content,
            "change_description": version.change_description,
            "created_at": version.created_at.isoformat(),
            "created_by": (
                {
                    "id": version.created_by.id,
                    "name": version.created_by.name,
                    "email": version.created_by.email,
                }
                if version.created_by
                else None
            ),
        }
    )


@api_v1_bp.route("/agents/global/rollback/<int:version_number>", methods=["POST"])
@require_api_auth(scopes=["write", "admin"])
@audit_api_request
def rollback_global_agents_context(version_number: int):
    """Rollback global agents context to a previous version.

    This creates a new version with the content from the specified version
    and updates the current global context.

    Request body (optional):
        {
            "description": "Optional rollback description"
        }

    Args:
        version_number: The version number to rollback to

    Returns:
        JSON response with updated global context
    """
    data = request.get_json() or {}
    description = data.get("description")

    # Get current user from API auth context
    from flask import g

    user_id = getattr(g, "api_user_id", None)

    try:
        global_context = global_agents_service.rollback_to_version(
            version_number, user_id, description
        )

        return jsonify(
            {
                "id": global_context.id,
                "content": global_context.content,
                "updated_at": global_context.updated_at.isoformat(),
                "updated_by": (
                    {
                        "id": global_context.updated_by.id,
                        "name": global_context.updated_by.name,
                        "email": global_context.updated_by.email,
                    }
                    if global_context.updated_by
                    else None
                ),
                "message": f"Rolled back to version {version_number}",
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@api_v1_bp.route("/agents/global/diff", methods=["GET"])
@require_api_auth(scopes=["read"])
@audit_api_request
def get_global_agents_diff():
    """Get diff between two versions of global agents context.

    Query parameters:
        from: Source version number (required)
        to: Target version number (required)

    Returns:
        JSON response with unified diff and statistics
    """
    from_version = request.args.get("from", type=int)
    to_version = request.args.get("to", type=int)

    if from_version is None or to_version is None:
        return (
            jsonify({"error": "Both 'from' and 'to' parameters are required"}),
            400,
        )

    try:
        diff_result = global_agents_service.get_version_diff(from_version, to_version)

        return jsonify(diff_result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
