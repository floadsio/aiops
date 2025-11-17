"""API v1 agent context management endpoints."""

from __future__ import annotations

from datetime import datetime

from flask import jsonify, request

from ...extensions import db
from ...models import GlobalAgentContext
from ...services.api_auth import audit_api_request, require_api_auth
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
    """Update or create the global agent context.

    Request body:
        {
            "content": "Global AGENTS.md content"
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

    # Get current user from API auth context
    from flask import g

    user_id = getattr(g, "api_user_id", None)

    # Check if global context already exists
    global_context = GlobalAgentContext.query.order_by(
        GlobalAgentContext.updated_at.desc()
    ).first()

    if global_context:
        # Update existing
        global_context.content = content
        global_context.updated_by_user_id = user_id
        global_context.updated_at = datetime.utcnow()
    else:
        # Create new
        global_context = GlobalAgentContext(
            content=content, updated_by_user_id=user_id
        )
        db.session.add(global_context)

    db.session.commit()

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
            "message": "Global agent context updated successfully",
        }
    )


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
