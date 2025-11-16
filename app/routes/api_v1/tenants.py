"""API v1 tenant management endpoints."""

from __future__ import annotations

from typing import Any

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

from ...constants import DEFAULT_TENANT_COLOR, sanitize_tenant_color
from ...extensions import db
from ...models import Tenant
from ...services.api_auth import audit_api_request, require_api_auth
from . import api_v1_bp


def _tenant_to_dict(tenant: Tenant, include_projects: bool = False) -> dict[str, Any]:
    """Convert Tenant model to dictionary.

    Args:
        tenant: The tenant model
        include_projects: Whether to include project list

    Returns:
        dict: Tenant data
    """
    data = {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description or "",
        "color": tenant.color or DEFAULT_TENANT_COLOR,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
    }

    if include_projects:
        from .projects import _project_to_dict
        data["projects"] = [_project_to_dict(p) for p in tenant.projects]

    return data


@api_v1_bp.get("/tenants")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_tenants():
    """List all tenants.

    Query params:
        include_projects (bool): Include project list for each tenant

    Returns:
        200: List of tenants
    """
    include_projects = request.args.get("include_projects", "false").lower() == "true"
    tenants = Tenant.query.order_by(Tenant.name).all()
    return jsonify({
        "tenants": [_tenant_to_dict(t, include_projects=include_projects) for t in tenants],
        "count": len(tenants),
    })


@api_v1_bp.get("/tenants/<int:tenant_id>")
@require_api_auth(scopes=["read"])
@audit_api_request
def get_tenant(tenant_id: int):
    """Get a specific tenant by ID.

    Args:
        tenant_id: Tenant ID

    Returns:
        200: Tenant data with projects
        404: Tenant not found
    """
    tenant = Tenant.query.get_or_404(tenant_id)
    return jsonify({"tenant": _tenant_to_dict(tenant, include_projects=True)})


@api_v1_bp.post("/tenants")
@require_api_auth(scopes=["write"])
@audit_api_request
def create_tenant():
    """Create a new tenant.

    Request body:
        name (str): Tenant name (required)
        description (str, optional): Tenant description
        color (str, optional): Color code (hex format)

    Returns:
        201: Created tenant
        400: Invalid request
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip() or None
    color = sanitize_tenant_color(data.get("color"))

    if not name:
        return jsonify({"error": "Tenant name is required"}), 400

    tenant = Tenant(name=name, description=description, color=color)
    db.session.add(tenant)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A tenant with this name already exists"}), 400

    return jsonify({"tenant": _tenant_to_dict(tenant)}), 201


@api_v1_bp.patch("/tenants/<int:tenant_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def update_tenant(tenant_id: int):
    """Update a tenant.

    Args:
        tenant_id: Tenant ID

    Request body:
        name (str, optional): New tenant name
        description (str, optional): New description
        color (str, optional): New color

    Returns:
        200: Updated tenant
        404: Tenant not found
    """
    tenant = Tenant.query.get_or_404(tenant_id)
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    if name and isinstance(name, str):
        tenant.name = name.strip()

    description = data.get("description")
    if description is not None:
        tenant.description = description.strip() or None

    color = data.get("color")
    if color:
        tenant.color = sanitize_tenant_color(color)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A tenant with this name already exists"}), 400

    return jsonify({"tenant": _tenant_to_dict(tenant)})


@api_v1_bp.delete("/tenants/<int:tenant_id>")
@require_api_auth(scopes=["admin"])
@audit_api_request
def delete_tenant(tenant_id: int):
    """Delete a tenant.

    Requires admin scope. This will cascade delete all projects and integrations.

    Args:
        tenant_id: Tenant ID

    Returns:
        204: Tenant deleted successfully
        404: Tenant not found
    """
    tenant = Tenant.query.get_or_404(tenant_id)
    db.session.delete(tenant)
    db.session.commit()
    return ("", 204)
