from __future__ import annotations

import os
from datetime import timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request
from flask_login import current_user  # type: ignore
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..ai_sessions import (
    close_session,
    create_session,
    get_session,
    resize_session,
    write_to_session,
)
from ..constants import DEFAULT_TENANT_COLOR, sanitize_tenant_color
from ..extensions import csrf, db
from ..models import ExternalIssue, Project, ProjectIntegration, Tenant, User
from ..services.git_service import ensure_repo_checkout, get_repo_status, run_git_action
from ..services.tmux_service import session_name_for_user
from ..services.issues.utils import normalize_issue_status

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.before_request
def require_authentication():
    """Authenticate requests using either session auth or API keys."""
    from ..services.api_auth import authenticate_request
    from flask import g

    # Try to authenticate via session or API key
    user, api_key = authenticate_request()

    if not user:
        return jsonify({"error": "Authentication required"}), 401

    # Store authenticated user in g for use in route handlers
    g.api_user = user
    g.api_key = api_key


def _current_user_obj():
    """Get the current user object for workspace operations."""
    from flask import g

    # First try g.api_user (set by authenticate_request in before_request)
    if hasattr(g, "api_user") and g.api_user:
        return g.api_user

    # Fall back to current_user for session-based auth
    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    return user_obj


def _tenant_to_dict(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description or "",
        "project_count": len(tenant.projects),
        "color": tenant.color or DEFAULT_TENANT_COLOR,
    }


def _project_to_dict(
    project: Project, *, include_status: bool = False
) -> dict[str, Any]:
    payload = {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "repo_url": project.repo_url,
        "default_branch": project.default_branch,
        "local_path": project.local_path,
        "tenant_id": project.tenant_id,
        "owner_id": project.owner_id,
        "tenant_color": (
            project.tenant.color if project.tenant else DEFAULT_TENANT_COLOR
        ),
    }
    if include_status:
        payload["git_status"] = get_repo_status(project, user=_current_user_obj())
    return payload


def _serialize_timestamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _issue_to_dict(issue: ExternalIssue) -> dict[str, Any]:
    integration = (
        issue.project_integration.integration if issue.project_integration else None
    )
    project = (
        issue.project_integration.project if issue.project_integration else None
    )
    tenant = project.tenant if project else None
    status_key, status_label = normalize_issue_status(issue.status)
    updated_reference = (
        issue.external_updated_at or issue.updated_at or issue.created_at
    )
    provider_key = (
        (integration.provider or "").lower()
        if integration and integration.provider
        else ""
    )
    return {
        "id": issue.id,
        "external_id": issue.external_id,
        "title": issue.title,
        "status": issue.status,
        "status_key": status_key,
        "status_label": status_label,
        "assignee": issue.assignee,
        "url": issue.url,
        "labels": issue.labels or [],
        "provider": integration.provider if integration else None,
        "provider_key": provider_key,
        "integration_name": integration.name if integration else None,
        "project_id": project.id if project else None,
        "project_name": project.name if project else None,
        "tenant_id": tenant.id if tenant else None,
        "tenant_name": tenant.name if tenant else None,
        "updated_at": _serialize_timestamp(updated_reference),
    }


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
    from flask import g

    # First try g.api_user (set by authenticate_request in before_request)
    if hasattr(g, "api_user") and g.api_user:
        return g.api_user.id

    # Fall back to current_user for session-based auth
    if hasattr(current_user, "model"):
        return getattr(current_user.model, "id", None)
    return getattr(current_user, "id", None)


def _ensure_project_access(project: Project) -> bool:
    from flask import g

    # Check if user is admin (try both g.api_user and current_user)
    is_admin = False
    if hasattr(g, "api_user") and g.api_user:
        is_admin = getattr(g.api_user, "is_admin", False)
    elif hasattr(current_user, "is_admin"):
        is_admin = current_user.is_admin

    if is_admin:
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


@api_bp.get("/issues")
def list_issues():
    if not current_user.is_admin:
        return jsonify({"error": "Access denied."}), 403

    status_filter = (request.args.get("status") or "").strip().lower()
    if status_filter == "all":
        status_filter = ""
    provider_filter = (
        (request.args.get("provider") or request.args.get("source") or "")
        .strip()
        .lower()
    )
    if provider_filter == "all":
        provider_filter = ""
    project_id = request.args.get("project_id", type=int)
    limit = request.args.get("limit", type=int)

    query = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration)
        .selectinload(ProjectIntegration.project)
        .selectinload(Project.tenant),
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    )
    if project_id is not None:
        query = query.join(ProjectIntegration).filter(
            ProjectIntegration.project_id == project_id
        )

    issues = query.all()
    payload: list[dict[str, Any]] = []
    for issue in issues:
        issue_payload = _issue_to_dict(issue)
        if status_filter and issue_payload["status_key"] != status_filter:
            continue
        if provider_filter and issue_payload.get("provider_key") != provider_filter:
            continue
        payload.append(issue_payload)

    if isinstance(limit, int) and limit > 0:
        payload = payload[:limit]

    return jsonify({"count": len(payload), "issues": payload})


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
        output = run_git_action(
            project, action, ref=ref, clean=clean, user=_current_user_obj()
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    return jsonify({"result": output})


@api_bp.post("/projects/<int:project_id>/workspace/init")
def init_project_workspace(project_id: int):
    """Initialize workspace for the current user and project."""
    from ..services.workspace_service import WorkspaceError, initialize_workspace

    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied."}), 403

    user = _current_user_obj()
    if not user:
        return jsonify({"error": "Unable to resolve current user."}), 400

    try:
        workspace_path = initialize_workspace(project, user)
        return jsonify(
            {
                "success": True,
                "path": str(workspace_path),
                "message": f"Workspace initialized at {workspace_path}",
            }
        )
    except WorkspaceError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Failed to initialize workspace: {exc}"}), 500


@api_bp.get("/projects/<int:project_id>/workspace/status")
def get_project_workspace_status(project_id: int):
    """Get workspace status for the current user and project."""
    from ..services.workspace_service import get_workspace_status

    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied."}), 403

    user = _current_user_obj()
    if not user:
        return jsonify({"error": "Unable to resolve current user."}), 400

    status = get_workspace_status(project, user)
    return jsonify(status)


@api_bp.get("/projects/<int:project_id>/ai/sessions")
def list_project_ai_sessions(project_id: int):
    """List active AI sessions for a project."""
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied."}), 403

    user_id = _current_user_id()

    # Import here to avoid circular imports
    from ..ai_sessions import list_active_sessions

    # Sessions run under the Flask app's system user (tmux owner)
    import pwd

    flask_system_user = pwd.getpwuid(os.getuid()).pw_name

    # Check if request wants all users' sessions (admin only)
    show_all_users = request.args.get("all_users", "false").lower() == "true"

    # Admins can see all users' sessions, regular users only see their own
    if show_all_users:
        # Verify user is admin (check both API user and session user)
        from flask_login import current_user
        is_admin = False
        if hasattr(g, "api_user") and g.api_user:
            is_admin = getattr(g.api_user, "is_admin", False)
        elif current_user and current_user.is_authenticated:
            is_admin = getattr(current_user, "is_admin", False)

        if not is_admin:
            return jsonify({"error": "Admin access required to view all users' sessions."}), 403
        # List all sessions for this project (no user filter)
        sessions = list_active_sessions(project_id=project_id)
    else:
        # List sessions for this project and user
        sessions = list_active_sessions(user_id=user_id, project_id=project_id)

    # Convert to JSON-serializable format
    session_list = []
    for session in sessions:
        session_list.append({
            "session_id": session.id,
            "project_id": session.project_id,
            "user_id": session.user_id,
            "issue_id": session.issue_id,
            "command": session.command,
            "tmux_target": session.tmux_target,
            "ssh_user": flask_system_user,
        })

    return jsonify({"sessions": session_list})


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
    issue_id = data.get("issue_id")  # Optional: track which issue this session is for

    user_id = _current_user_id()
    if user_id is None:
        try:
            user_id = int(current_user.get_id())  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return jsonify({"error": "Unable to resolve current user."}), 400

    # Check if there's already an active session for this issue
    from ..ai_sessions import find_session_for_issue
    existing_session = None
    if issue_id:
        existing_session = find_session_for_issue(issue_id, user_id, project_id)

    # For SSH attachment, return the system user running the Flask app (e.g., syseng)
    # This is the user that owns the tmux server process, not the user inside the pane
    import pwd
    flask_system_user = pwd.getpwuid(os.getuid()).pw_name

    if existing_session:
        # Reuse existing session
        session = existing_session
        was_created = False
    else:
        # Create new session
        # Use the current user's model directly for tmux session mapping
        session_user = getattr(current_user, "model", None)
        if not session_user:
            session_user = User.query.get(user_id)
        tmux_session_name = session_name_for_user(session_user)

        # Populate AGENTS.override.md for the issue before starting session
        if issue_id:
            from ..services.agent_context import write_tracked_issue_context
            try:
                # Get the issue with all related data
                issue = ExternalIssue.query.get(issue_id)
                if issue:
                    # Get all issues for the project to include in context
                    all_issues = ExternalIssue.query.filter(
                        ExternalIssue.project_integration.has(project_id=project.id)
                    ).all()

                    # Write context to user's workspace
                    write_tracked_issue_context(
                        project,
                        issue,
                        all_issues,
                        identity_user=session_user,
                    )
            except Exception as exc:
                # Log but don't fail session creation if context write fails
                current_app.logger.warning(
                    "Failed to populate AGENTS.override.md for issue %s: %s",
                    issue_id,
                    exc,
                )

        try:
            session = create_session(
                project,
                user_id,
                tool=tool,
                command=command,
                rows=rows if isinstance(rows, int) else None,
                cols=cols if isinstance(cols, int) else None,
                tmux_target=tmux_target,
                tmux_session_name=tmux_session_name,
                issue_id=issue_id,
            )
            was_created = True
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    # Only send prompt if a new session was created
    if was_created and isinstance(prompt, str) and prompt.strip():
        write_to_session(session, prompt + "\n")

    response_data = {
        "session_id": session.id,
        "tmux_target": session.tmux_target,  # Actual tmux session:window to attach to
        "ssh_user": flask_system_user,  # User to SSH as (owns tmux server)
        "existing": not was_created,  # Indicate if this is an existing session
        "context_populated": was_created and issue_id is not None,  # Whether AGENTS.override.md was populated
    }

    return jsonify(response_data), 201


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


@api_bp.get("/ai/sessions")
def list_ai_sessions():
    """Get AI session history for the current user."""
    from ..services.ai_session_service import get_session_summary, get_user_sessions

    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"error": "Unable to resolve current user."}), 400

    # Get query parameters for filtering
    project_id = request.args.get("project_id", type=int)
    tool = request.args.get("tool")
    active_only = request.args.get("active_only", "false").lower() == "true"
    limit = request.args.get("limit", type=int, default=50)

    # Fetch sessions from database
    sessions = get_user_sessions(
        user_id=user_id,
        project_id=project_id,
        tool=tool,
        active_only=active_only,
    )

    # Limit results
    sessions = sessions[:limit]

    # Convert to summary format
    session_list = [get_session_summary(session) for session in sessions]

    return jsonify(
        {
            "sessions": session_list,
            "count": len(session_list),
        }
    )


@api_bp.post("/ai/sessions/<int:db_session_id>/resume")
def resume_ai_session(db_session_id: int):
    """Resume a previous AI session in its related tmux window."""
    from ..models import AISession as AISessionModel
    from ..services.ai_session_service import build_resume_command

    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"error": "Unable to resolve current user."}), 400

    # Fetch the session from database
    db_session = AISessionModel.query.get_or_404(db_session_id)

    # Verify user has access
    if db_session.user_id != user_id and not current_user.is_admin:
        return jsonify({"error": "Access denied."}), 403

    # Get the project
    project = Project.query.get_or_404(db_session.project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied to project."}), 403

    # Build the resume command
    resume_command = build_resume_command(db_session)

    # Get request parameters for the new session
    data = request.get_json(silent=True) or {}
    rows = data.get("rows")
    cols = data.get("cols")

    # Use the same tmux target if available
    tmux_target = db_session.tmux_target

    # Get session name for user
    session_user = getattr(current_user, "model", None)
    if not session_user:
        session_user = User.query.get(user_id)
    tmux_session_name = session_name_for_user(session_user)

    try:
        # Create a new AI session with the resume command
        session = create_session(
            project,
            user_id,
            tool=db_session.tool,
            command=resume_command,
            rows=rows if isinstance(rows, int) else None,
            cols=cols if isinstance(cols, int) else None,
            tmux_target=tmux_target,
            tmux_session_name=tmux_session_name,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "session_id": session.id,
            "message": f"Resumed {db_session.tool} session in project {project.name}",
        }
    ), 201


csrf.exempt(api_bp)
