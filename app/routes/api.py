from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from ..constants import DEFAULT_TENANT_COLOR, sanitize_tenant_color
from ..ai_sessions import close_session, create_session, get_session, resize_session, write_to_session
from ..extensions import csrf, db
from ..models import Project, Tenant, User
from ..services.git_service import ensure_repo_checkout, get_repo_status, run_git_action

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.before_request
def require_authentication():
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401


def _tenant_to_dict(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description or "",
        "project_count": len(tenant.projects),
        "color": tenant.color or DEFAULT_TENANT_COLOR,
    }


def _project_to_dict(project: Project, *, include_status: bool = False) -> dict[str, Any]:
    payload = {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "repo_url": project.repo_url,
        "default_branch": project.default_branch,
        "local_path": project.local_path,
        "tenant_id": project.tenant_id,
        "owner_id": project.owner_id,
        "tenant_color": (project.tenant.color if project.tenant else DEFAULT_TENANT_COLOR),
    }
    if include_status:
        payload["git_status"] = get_repo_status(project)
    return payload


def _slugify(name: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in name)
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return cleaned or "project"


@api_bp.get("/tenants")
def list_tenants():
    tenants = Tenant.query.order_by(Tenant.name).all()
    return jsonify({"tenants": [_tenant_to_dict(t) for t in tenants]})


@api_bp.post("/tenants")
def create_tenant():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip() or None
    color = sanitize_tenant_color(data.get("color"))

    if not name:
        return jsonify({"error": "Tenant name is required."}), 400

    tenant = Tenant(name=name, description=description, color=color)
    db.session.add(tenant)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Tenant name already exists."}), 400

    return jsonify({"tenant": _tenant_to_dict(tenant)}), 201


@api_bp.get("/tenants/<int:tenant_id>")
def get_tenant(tenant_id: int):
    tenant = Tenant.query.get_or_404(tenant_id)
    projects = [_project_to_dict(p) for p in tenant.projects]
    payload = _tenant_to_dict(tenant)
    payload["projects"] = projects
    return jsonify({"tenant": payload})


@api_bp.get("/projects")
def list_projects():
    tenant_id = request.args.get("tenant_id", type=int)
    query = Project.query
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)
    projects = query.order_by(Project.created_at.desc()).all()
    return jsonify({"projects": [_project_to_dict(p) for p in projects]})


def _resolve_project_owner(owner_id: int | None) -> User | None:
    if owner_id is None:
        return None
    return User.query.get(owner_id)


def _current_user_id() -> int | None:
    if hasattr(current_user, "model"):
        return getattr(current_user.model, "id", None)
    return getattr(current_user, "id", None)


def _ensure_project_access(project: Project) -> bool:
    if current_user.is_admin:
        return True
    return project.owner_id == _current_user_id()


@api_bp.post("/projects")
def create_project():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    repo_url = (data.get("repo_url") or "").strip()
    default_branch = (data.get("default_branch") or "").strip() or "main"
    description = (data.get("description") or "").strip() or None
    tenant_id = data.get("tenant_id")
    owner_id = data.get("owner_id")

    if not name or not repo_url:
        return jsonify({"error": "Project name and repo_url are required."}), 400
    if not isinstance(tenant_id, int):
        return jsonify({"error": "tenant_id must be provided."}), 400

    tenant = Tenant.query.get(tenant_id)
    if tenant is None:
        return jsonify({"error": "Tenant not found."}), 404

    owner = _resolve_project_owner(owner_id)
    if owner is None:
        return jsonify({"error": "Owner not found."}), 404

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
        return jsonify({"error": "A project with this name already exists."}), 400

    try:
        ensure_repo_checkout(project)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(
            "Failed to prepare repository for project %s: %s", project.name, exc
        )

    return jsonify({"project": _project_to_dict(project)}), 201


@api_bp.get("/projects/<int:project_id>")
def get_project(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied."}), 403
    return jsonify({"project": _project_to_dict(project, include_status=True)})


@api_bp.post("/projects/<int:project_id>/git")
def project_git_action(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied."}), 403

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    ref = (data.get("ref") or "").strip() or None
    clean = bool(data.get("clean", False))

    if action not in {"pull", "push", "status"}:
        return jsonify({"error": "Unsupported git action."}), 400

    try:
        output = run_git_action(project, action, ref=ref, clean=clean)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    return jsonify({"result": output})


@api_bp.post("/projects/<int:project_id>/ai/sessions")
def start_project_ai_session(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied."}), 403

    data = request.get_json(silent=True) or {}
    tool = data.get("tool")
    command = data.get("command")
    prompt = data.get("prompt")
    rows = data.get("rows")
    cols = data.get("cols")
    tmux_target = (data.get("tmux_target") or "").strip() or None

    user_id = _current_user_id()
    if user_id is None:
        try:
            user_id = int(current_user.get_id())  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return jsonify({"error": "Unable to resolve current user."}), 400

    try:
        session = create_session(
            project,
            user_id,
            tool=tool,
            command=command,
            rows=rows if isinstance(rows, int) else None,
            cols=cols if isinstance(cols, int) else None,
            tmux_target=tmux_target,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if isinstance(prompt, str) and prompt.strip():
        write_to_session(session, prompt + "\n")

    return jsonify({"session_id": session.id}), 201


def _get_project_session(project_id: int, session_id: str):
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return None, jsonify({"error": "Access denied."}), 403

    session = get_session(session_id)
    if session is None or session.project_id != project.id:
        return None, jsonify({"error": "Session not found."}), 404
    return session, None, None


@api_bp.post("/projects/<int:project_id>/ai/sessions/<session_id>/input")
def send_project_ai_input(project_id: int, session_id: str):
    session, error_response, status = _get_project_session(project_id, session_id)
    if error_response is not None:
        return error_response, status

    data = request.get_json(silent=True) or {}
    text = data.get("data")
    if not isinstance(text, str) or not text:
        return jsonify({"error": "data must be a non-empty string."}), 400

    write_to_session(session, text)
    return jsonify({"status": "ok"})


@api_bp.post("/projects/<int:project_id>/ai/sessions/<session_id>/resize")
def resize_project_ai_session(project_id: int, session_id: str):
    session, error_response, status = _get_project_session(project_id, session_id)
    if error_response is not None:
        return error_response, status

    data = request.get_json(silent=True) or {}
    rows = data.get("rows")
    cols = data.get("cols")
    if not isinstance(rows, int) or not isinstance(cols, int) or rows <= 0 or cols <= 0:
        return jsonify({"error": "rows and cols must be positive integers."}), 400

    resize_session(session, rows, cols)
    return ("", 204)


@api_bp.delete("/projects/<int:project_id>/ai/sessions/<session_id>")
def stop_project_ai_session(project_id: int, session_id: str):
    session, error_response, status = _get_project_session(project_id, session_id)
    if error_response is not None:
        return error_response, status

    close_session(session)
    return ("", 204)


csrf.exempt(api_bp)
