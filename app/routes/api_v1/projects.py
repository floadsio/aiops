"""API v1 project management endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ...extensions import db
from ...models import Project, Tenant, User
from ...services.api_auth import audit_api_request, require_api_auth
from ...services.git_service import ensure_repo_checkout, get_repo_status
from ...services.tmux_service import TmuxServiceError, close_tmux_target, respawn_pane
from . import api_v1_bp


def _project_to_dict(project: Project, include_status: bool = False) -> dict[str, Any]:
    """Convert Project model to dictionary.

    Args:
        project: The project model
        include_status: Whether to include git status

    Returns:
        dict: Project data
    """
    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "repo_url": project.repo_url,
        "default_branch": project.default_branch,
        "local_path": project.local_path,
        "tenant_id": project.tenant_id,
        "tenant_name": project.tenant.name if project.tenant else None,
        "owner_id": project.owner_id,
        "owner_name": project.owner.name if project.owner else None,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }

    if include_status:
        user = g.api_user
        data["git_status"] = get_repo_status(project, user=user)

    return data


def _slugify(name: str) -> str:
    """Convert a name to a URL-safe slug."""
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in name)
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return cleaned or "project"


def _ensure_project_access(project: Project, user: User) -> bool:
    """Check if user has access to a project."""
    if user.is_admin:
        return True
    return project.owner_id == user.id


@api_v1_bp.get("/projects")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_projects():
    """List all projects.

    Query params:
        tenant_id (int, optional): Filter by tenant
        include_status (bool): Include git status for each project

    Returns:
        200: List of projects
    """
    tenant_id = request.args.get("tenant_id", type=int)
    include_status = request.args.get("include_status", "false").lower() == "true"

    query = Project.query
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)

    projects = query.order_by(Project.created_at.desc()).all()
    return jsonify({
        "projects": [_project_to_dict(p, include_status=include_status) for p in projects],
        "count": len(projects),
    })


@api_v1_bp.get("/projects/<int:project_id>")
@require_api_auth(scopes=["read"])
@audit_api_request
def get_project(project_id: int):
    """Get a specific project by ID.

    Args:
        project_id: Project ID

    Returns:
        200: Project data with git status
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    user = g.api_user

    if not _ensure_project_access(project, user):
        return jsonify({"error": "Access denied"}), 403

    return jsonify({"project": _project_to_dict(project, include_status=True)})


@api_v1_bp.post("/projects")
@require_api_auth(scopes=["write"])
@audit_api_request
def create_project():
    """Create a new project.

    Request body:
        name (str): Project name (required)
        repo_url (str): Git repository URL (required)
        tenant_id (int): Tenant ID (required)
        description (str, optional): Project description
        default_branch (str, optional): Default git branch (default: main)
        owner_id (int, optional): Owner user ID (defaults to current user)

    Returns:
        201: Created project
        400: Invalid request
        404: Tenant or owner not found
    """
    user = g.api_user
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    repo_url = (data.get("repo_url") or "").strip()
    tenant_id = data.get("tenant_id")
    description = (data.get("description") or "").strip() or None
    default_branch = (data.get("default_branch") or "").strip() or "main"
    owner_id = data.get("owner_id", user.id)

    if not name or not repo_url:
        return jsonify({"error": "Project name and repo_url are required"}), 400
    if not isinstance(tenant_id, int):
        return jsonify({"error": "tenant_id must be provided"}), 400

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404

    owner = User.query.get(owner_id)
    if not owner:
        return jsonify({"error": "Owner not found"}), 404

    # Create local path
    storage_root = Path(current_app.config["REPO_STORAGE_PATH"])
    storage_root.mkdir(parents=True, exist_ok=True)
    slug = _slugify(name)
    local_path = storage_root / slug

    project = Project(
        name=name,
        repo_url=repo_url,
        default_branch=default_branch,
        description=description,
        tenant=tenant,
        owner=owner,
        local_path=str(local_path),
    )
    db.session.add(project)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A project with this name already exists"}), 400

    # Try to clone the repository
    try:
        ensure_repo_checkout(project)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(
            "Failed to prepare repository for project %s: %s", project.name, exc
        )

    return jsonify({"project": _project_to_dict(project)}), 201


@api_v1_bp.patch("/projects/<int:project_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def update_project(project_id: int):
    """Update a project.

    Args:
        project_id: Project ID

    Request body:
        name (str, optional): New project name
        description (str, optional): New description
        repo_url (str, optional): New repository URL
        default_branch (str, optional): New default branch

    Returns:
        200: Updated project
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    user = g.api_user

    if not _ensure_project_access(project, user):
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}

    name = data.get("name")
    if name and isinstance(name, str):
        project.name = name.strip()

    description = data.get("description")
    if description is not None:
        project.description = description.strip() or None

    repo_url = data.get("repo_url")
    if repo_url and isinstance(repo_url, str):
        project.repo_url = repo_url.strip()

    default_branch = data.get("default_branch")
    if default_branch and isinstance(default_branch, str):
        project.default_branch = default_branch.strip()

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A project with this name already exists"}), 400

    return jsonify({"project": _project_to_dict(project)})


@api_v1_bp.delete("/projects/<int:project_id>")
@require_api_auth(scopes=["admin"])
@audit_api_request
def delete_project(project_id: int):
    """Delete a project.

    Requires admin scope. This will cascade delete all related data.

    Args:
        project_id: Project ID

    Returns:
        204: Project deleted successfully
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    user = g.api_user

    if not user.is_admin:
        return jsonify({"error": "Admin access required"}), 403

    db.session.delete(project)
    db.session.commit()
    return ("", 204)


@api_v1_bp.post("/projects/<int:project_id>/tmux/close")
@require_api_auth(scopes=["write"])
@audit_api_request
def close_tmux_window_api(project_id: int):
    """Close a tmux window for a project.

    Args:
        project_id: Project ID

    Request body:
        tmux_target (str): Tmux target in format "session:window"

    Returns:
        200: Success
        400: Invalid tmux target
        403: Access denied
        404: Project not found
        500: Tmux operation failed
    """
    project = Project.query.get_or_404(project_id)
    user = g.api_user

    if not _ensure_project_access(project, user):
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}
    tmux_target = (data.get("tmux_target") or "").strip()

    if not tmux_target:
        return jsonify({"error": "Invalid tmux target"}), 400

    # Get linux username from tmux target (format: username:session-window)
    linux_username = None
    if ":" in tmux_target:
        linux_username = tmux_target.split(":")[0]

    try:
        close_tmux_target(tmux_target, linux_username=linux_username)
        return jsonify({"success": True})
    except TmuxServiceError as exc:
        return jsonify({"error": str(exc)}), 500


@api_v1_bp.post("/projects/<int:project_id>/tmux/respawn")
@require_api_auth(scopes=["write"])
@audit_api_request
def respawn_tmux_pane_api(project_id: int):
    """Respawn a dead tmux pane for a project.

    Args:
        project_id: Project ID

    Request body:
        tmux_target (str): Tmux target in format "session:window"

    Returns:
        200: Success
        400: Invalid tmux target
        403: Access denied
        404: Project not found
        500: Tmux operation failed
    """
    project = Project.query.get_or_404(project_id)
    user = g.api_user

    if not _ensure_project_access(project, user):
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}
    tmux_target = (data.get("tmux_target") or "").strip()

    if not tmux_target:
        return jsonify({"error": "Invalid tmux target"}), 400

    # Get linux username from tmux target (format: username:session-window)
    linux_username = None
    if ":" in tmux_target:
        linux_username = tmux_target.split(":")[0]

    try:
        respawn_pane(tmux_target, linux_username=linux_username)
        return jsonify({"success": True})
    except TmuxServiceError as exc:
        return jsonify({"error": str(exc)}), 500
