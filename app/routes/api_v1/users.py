"""AIops REST API v1 - Users endpoints.

This module provides endpoints for user management.
"""

from __future__ import annotations

from flask import g, jsonify
from flask_login import current_user

from . import api_v1_bp


@api_v1_bp.get("/users")
def list_users():
    """List all users (admin only for security)."""
    from ...models import User

    # Check if current user is admin
    is_admin = False
    if hasattr(g, "api_user") and g.api_user:
        is_admin = getattr(g.api_user, "is_admin", False)
    elif current_user and current_user.is_authenticated:
        is_admin = getattr(current_user, "is_admin", False)

    if not is_admin:
        return jsonify({"error": "Admin access required to list users."}), 403

    users = User.query.order_by(User.email).all()
    return jsonify({
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "is_admin": u.is_admin,
            }
            for u in users
        ]
    })
