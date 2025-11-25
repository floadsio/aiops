from __future__ import annotations

import os
import re
import uuid
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
    find_session_for_issue,
    resize_session,
    write_to_session,
    _resolve_command,
)
from ..constants import DEFAULT_TENANT_COLOR, sanitize_tenant_color
from ..extensions import csrf, db
from ..models import ExternalIssue, Project, ProjectIntegration, Tenant, User
from ..services.git_service import ensure_repo_checkout, get_repo_status, run_git_action
from ..services.tmux_service import session_name_for_user
from ..services.issues.utils import normalize_issue_status
from ..services.activity_logger import log_api_activity
from ..services.activity_service import ActivityType, ResourceType

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return slug or "session"


def _generate_tmux_target(session_name: str, project: Project, tool: str | None, issue_id: int | None) -> str:
    base = _slugify(getattr(project, "name", "") or f"project-{getattr(project, 'id', '')}")
    parts: list[str] = [base]
    if issue_id:
        parts.append(f"issue{issue_id}")
    if tool:
        parts.append(_slugify(tool))
    parts.append(uuid.uuid4().hex[:6])
    window_name = "-".join(part for part in parts if part)
    return f"{session_name}:{window_name}"


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
        "tenant_name": project.tenant.name if project.tenant else "Unknown",
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


@api_bp.get("/users")
def list_users():
    """List all users (admin only for security)."""
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
@log_api_activity(
    action_type=ActivityType.PROJECT_CREATE,
    resource_type=ResourceType.PROJECT,
    get_resource_id=lambda data: data.get("project", {}).get("id"),
    get_resource_name=lambda data: data.get("project", {}).get("name"),
    get_description=lambda data: f"Created project: {data.get('project', {}).get('name')}",
)
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
    # Check admin status from either API key or session
    is_admin = False
    if hasattr(g, "api_user") and g.api_user:
        is_admin = getattr(g.api_user, "is_admin", False)
    elif current_user and current_user.is_authenticated:
        is_admin = getattr(current_user, "is_admin", False)

    if not is_admin:
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
    from ..services.activity_service import log_activity

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

        # Log git operations (except status which is read-only)
        if action in {"pull", "push"}:
            action_type_map = {
                "pull": ActivityType.GIT_PULL,
                "push": ActivityType.GIT_PUSH,
            }
            user_id = g.api_user.id if hasattr(g, "api_user") and g.api_user else None
            user_agent = request.headers.get("User-Agent", "").lower()
            source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"

            log_activity(
                action_type=action_type_map.get(action, f"git.{action}"),
                user_id=user_id,
                resource_type=ResourceType.PROJECT,
                resource_id=project.id,
                resource_name=project.name,
                status="success",
                description=f"Git {action} on project {project.name}",
                source=source,
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
    from ..services.activity_service import log_activity

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
    requested_user_id = data.get("user_id")  # Optional: admin can start session as another user
    permission_mode = data.get("permission_mode")  # Optional: override permission mode (e.g., "yolo")
    resolved_command = None

    try:
        resolved_command = _resolve_command(tool, command, permission_mode=permission_mode)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    user_id = _current_user_id()
    if user_id is None:
        try:
            user_id = int(current_user.get_id())  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return jsonify({"error": "Unable to resolve current user."}), 400

    # Allow admins to start sessions as other users
    if requested_user_id and requested_user_id != user_id:
        # Check if current user is admin
        is_admin = False
        if hasattr(g, "api_user") and g.api_user:
            is_admin = getattr(g.api_user, "is_admin", False)
        elif current_user and current_user.is_authenticated:
            is_admin = getattr(current_user, "is_admin", False)

        if not is_admin:
            return jsonify({"error": "Admin access required to start sessions as other users."}), 403

        # Verify the requested user exists
        target_user = User.query.get(requested_user_id)
        if not target_user:
            return jsonify({"error": f"User ID {requested_user_id} not found."}), 404

        user_id = requested_user_id

    # Check if there's already an active session for this issue with the same tool/command
    existing_session = None
    if issue_id:
        existing_session = find_session_for_issue(
            issue_id,
            user_id,
            project_id,
            expected_tool=tool,
            expected_command=resolved_command,
        )

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
        if not tmux_target:
            tmux_target = _generate_tmux_target(
                tmux_session_name,
                project,
                tool,
                issue_id,
            )

        # Populate AGENTS.override.md before starting session
        # - With issue: include global + issue-specific context
        # - Without issue: include only global context
        context_sources: list[str] = []
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

                    # Write global + issue context to user's workspace
                    _, context_sources = write_tracked_issue_context(
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
        else:
            from ..services.agent_context import write_global_context_only
            try:
                # Write only global context to user's workspace
                _, context_sources = write_global_context_only(
                    project,
                    identity_user=session_user,
                )
            except Exception as exc:
                # Log but don't fail session creation if context write fails
                current_app.logger.warning(
                    "Failed to populate AGENTS.override.md with global context: %s",
                    exc,
                )

        try:
            # Use persistent sessions if enabled
            if current_app.config.get("ENABLE_PERSISTENT_SESSIONS", False):
                from ..ai_sessions import create_persistent_session
                session = create_persistent_session(
                    project,
                    user_id,
                    tool=tool,
                    command=command,
                    rows=rows if isinstance(rows, int) else None,
                    cols=cols if isinstance(cols, int) else None,
                    tmux_target=tmux_target,
                    tmux_session_name=tmux_session_name,
                    issue_id=issue_id,
                    permission_mode=permission_mode,
                )
            else:
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
                    permission_mode=permission_mode,
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
        "context_populated": was_created and len(context_sources) > 0,  # Whether AGENTS.override.md was populated
        "context_sources": context_sources if was_created else [],  # List of sources that were merged
    }

    # Log session activity
    api_user_id = g.api_user.id if hasattr(g, "api_user") and g.api_user else None
    user_agent = request.headers.get("User-Agent", "").lower()
    source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"

    if was_created:
        # Log new session creation
        log_activity(
            action_type=ActivityType.SESSION_START,
            user_id=api_user_id,
            resource_type=ResourceType.PROJECT,
            resource_id=project.id,
            resource_name=project.name,
            status="success",
            description=f"Started AI session for project {project.name}",
            extra_data={"tool": tool, "issue_id": issue_id} if tool else {"issue_id": issue_id} if issue_id else None,
            source=source,
        )
    else:
        # Log attach to existing session
        log_activity(
            action_type=ActivityType.SESSION_ATTACH,
            user_id=api_user_id,
            resource_type=ResourceType.PROJECT,
            resource_id=project.id,
            resource_name=project.name,
            status="success",
            description=f"Attached to existing AI session for project {project.name}",
            extra_data={"tool": tool, "issue_id": issue_id, "session_id": session.id} if tool else {"issue_id": issue_id, "session_id": session.id} if issue_id else {"session_id": session.id},
            source=source,
        )

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
    """Get AI session history for the current user or all users (admin only)."""
    from ..services.ai_session_service import get_session_summary, get_user_sessions

    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"error": "Unable to resolve current user."}), 400

    # Get query parameters for filtering
    project_id = request.args.get("project_id", type=int)
    tool = request.args.get("tool")
    active_only = request.args.get("active_only", "false").lower() == "true"
    limit = request.args.get("limit", type=int, default=50)
    all_users = request.args.get("all_users", "false").lower() == "true"

    # Check admin permission for all_users
    if all_users:
        is_admin = False
        if hasattr(g, "api_user") and g.api_user:
            is_admin = getattr(g.api_user, "is_admin", False)
        elif current_user and current_user.is_authenticated:
            is_admin = getattr(current_user, "is_admin", False)

        if not is_admin:
            return jsonify({"error": "Admin access required to view all users' sessions."}), 403

    # Fetch sessions from database
    sessions = get_user_sessions(
        user_id=user_id if not all_users else None,
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


@api_bp.get("/ai/sessions/<int:db_session_id>/validate")
def validate_ai_session(db_session_id: int):
    """Validate if a session's tmux target still exists and mark inactive if not."""
    from ..models import AISession as AISessionModel
    from ..ai_sessions import session_exists

    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"error": "Unable to resolve current user."}), 400

    # Fetch the session from database
    db_session = AISessionModel.query.get_or_404(db_session_id)

    # Check admin permission for other users' sessions
    is_admin = False
    if hasattr(g, "api_user") and g.api_user:
        is_admin = getattr(g.api_user, "is_admin", False)
    elif current_user and current_user.is_authenticated:
        is_admin = getattr(current_user, "is_admin", False)

    # Verify user has access
    if db_session.user_id != user_id and not is_admin:
        return jsonify({"error": "Access denied."}), 403

    # Check if the tmux target exists
    if db_session.tmux_target:
        exists = session_exists(db_session.tmux_target)

        # If session doesn't exist but DB says it's active, mark it inactive
        if not exists and db_session.is_active:
            from ..services.ai_session_service import end_session
            end_session(db_session.id)

            return jsonify({
                "exists": False,
                "marked_inactive": True,
                "message": "Session no longer exists and has been marked inactive"
            })

        return jsonify({
            "exists": exists,
            "marked_inactive": False
        })

    # No tmux target means we can't validate
    return jsonify({
        "exists": False,
        "marked_inactive": False,
        "message": "No tmux target associated with this session"
    })


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


@api_bp.post("/ai/sessions/<int:db_session_id>/attach")
def track_session_attach(db_session_id: int):
    """Track when a user attaches to an existing session (CLI usage).

    This endpoint doesn't perform the attach operation itself (that's done via SSH+tmux),
    but logs the activity for tracking purposes.
    """
    from ..models import AISession as AISessionModel
    from ..services.activity_service import log_activity

    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"error": "Unable to resolve current user."}), 400

    # Fetch the session from database
    db_session = AISessionModel.query.get_or_404(db_session_id)

    # Verify user has access (admins can attach to any session)
    is_admin = False
    if hasattr(g, "api_user") and g.api_user:
        is_admin = getattr(g.api_user, "is_admin", False)
    elif current_user and current_user.is_authenticated:
        is_admin = getattr(current_user, "is_admin", False)

    if db_session.user_id != user_id and not is_admin:
        return jsonify({"error": "Access denied."}), 403

    # Get the project
    project = Project.query.get_or_404(db_session.project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied to project."}), 403

    # Log the attach activity
    api_user_id = g.api_user.id if hasattr(g, "api_user") and g.api_user else None
    user_agent = request.headers.get("User-Agent", "").lower()
    source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"

    log_activity(
        action_type=ActivityType.SESSION_ATTACH,
        user_id=api_user_id,
        resource_type=ResourceType.PROJECT,
        resource_id=project.id,
        resource_name=project.name,
        status="success",
        description=f"Attached to AI session for project {project.name}",
        extra_data={"tool": db_session.tool, "session_id": db_session.id, "tmux_target": db_session.tmux_target},
        source=source,
    )

    return jsonify(
        {
            "success": True,
            "message": f"Session attach tracked for project {project.name}",
        }
    ), 200


@api_bp.post("/issues/<int:issue_id>/remap")
def remap_issue(issue_id: int):
    """Remap an issue to a different aiops project.

    This updates the internal aiops mapping only - the external issue tracker
    (GitHub/GitLab/Jira) remains unchanged.
    """
    from ..services.activity_service import log_activity

    # Check admin status
    is_admin = False
    if hasattr(g, "api_user") and g.api_user:
        is_admin = getattr(g.api_user, "is_admin", False)
    elif current_user and current_user.is_authenticated:
        is_admin = getattr(current_user, "is_admin", False)

    if not is_admin:
        return jsonify({"error": "Admin access required to remap issues."}), 403

    # Get the issue
    issue = ExternalIssue.query.get_or_404(issue_id)

    # Get target project ID from request
    data = request.get_json(silent=True) or {}
    target_project_id = data.get("project_id")

    if not isinstance(target_project_id, int):
        return jsonify({"error": "project_id must be provided as an integer."}), 400

    # Get target project
    target_project = Project.query.get(target_project_id)
    if not target_project:
        return jsonify({"error": "Target project not found."}), 404

    # Get current integration and project
    old_project_integration = issue.project_integration
    old_project = old_project_integration.project if old_project_integration else None
    old_integration = old_project_integration.integration if old_project_integration else None

    # Check if the issue is already in the target project
    if old_project and old_project.id == target_project_id:
        return jsonify({"error": "Issue is already in the target project."}), 400

    # Find or create a ProjectIntegration for the target project with the same integration
    if not old_integration:
        return jsonify({"error": "Issue has no integration associated."}), 400

    target_project_integration = ProjectIntegration.query.filter_by(
        project_id=target_project_id,
        integration_id=old_integration.id
    ).first()

    if not target_project_integration:
        # Create a new ProjectIntegration
        # Use target project's repo URL or name as external identifier
        external_id = target_project.repo_url or target_project.name
        target_project_integration = ProjectIntegration(
            project_id=target_project_id,
            integration_id=old_integration.id,
            external_identifier=external_id
        )
        db.session.add(target_project_integration)
        db.session.flush()  # Get the ID without committing

    # Update the issue's project_integration_id
    old_project_integration_id = issue.project_integration_id
    issue.project_integration_id = target_project_integration.id

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        return jsonify({"error": f"Failed to remap issue: {exc}"}), 400

    # Log the remapping activity
    api_user_id = g.api_user.id if hasattr(g, "api_user") and g.api_user else None
    user_agent = request.headers.get("User-Agent", "").lower()
    source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"

    log_activity(
        action_type="issue.remap",
        user_id=api_user_id,
        resource_type=ResourceType.PROJECT,
        resource_id=target_project.id,
        resource_name=target_project.name,
        status="success",
        description=f"Remapped issue #{issue.external_id} from {old_project.name if old_project else 'unknown'} to {target_project.name}",
        extra_data={
            "issue_id": issue.id,
            "external_id": issue.external_id,
            "old_project_id": old_project.id if old_project else None,
            "old_project_name": old_project.name if old_project else None,
            "new_project_id": target_project.id,
            "new_project_name": target_project.name,
            "old_project_integration_id": old_project_integration_id,
            "new_project_integration_id": target_project_integration.id,
        },
        source=source,
    )

    return jsonify({
        "success": True,
        "issue": _issue_to_dict(issue),
        "message": f"Issue #{issue.external_id} remapped to project {target_project.name}"
    }), 200


@api_bp.get("/activities")
def list_activities_api():
    """List activities via API (for CLI)."""
    from ..services.activity_service import get_recent_activities

    # Get filter parameters
    limit_str = request.args.get("limit", "50")
    try:
        limit = min(int(limit_str), 1000)
    except ValueError:
        limit = 50

    user_id_str = request.args.get("user_id")
    user_id = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
        except ValueError:
            pass

    action_type = request.args.get("action_type") or None
    resource_type = request.args.get("resource_type") or None
    status = request.args.get("status") or None
    source = request.args.get("source") or None

    # Fetch activities
    activities = get_recent_activities(
        limit=limit,
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        status=status,
        source=source,
    )

    # Convert to JSON
    activity_list = []
    for activity in activities:
        activity_dict = {
            "id": activity.id,
            "timestamp": activity.created_at.isoformat() if activity.created_at else None,
            "user_id": activity.user_id,
            "user_email": activity.user.email if activity.user else None,
            "action_type": activity.action_type,
            "resource_type": activity.resource_type,
            "resource_id": activity.resource_id,
            "resource_name": activity.resource_name,
            "status": activity.status,
            "description": activity.description,
            "extra_data": activity.extra_data,
            "error_message": activity.error_message,
            "ip_address": activity.ip_address,
            "source": activity.source,
        }
        activity_list.append(activity_dict)

    return jsonify({"count": len(activity_list), "activities": activity_list})


csrf.exempt(api_bp)
