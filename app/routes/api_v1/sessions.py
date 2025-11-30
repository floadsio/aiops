"""AIops API v1 - Session Management Routes.

This module provides REST API endpoints for managing AI sessions,
including creating, listing, validating, and controlling sessions.
"""

from __future__ import annotations

import os
import re
import uuid

from flask import current_app, g, jsonify, request
from flask_login import current_user  # type: ignore

from . import api_v1_bp
from ...ai_sessions import (
    close_session,
    create_session,
    find_session_for_issue,
    get_session,
    resize_session,
    session_exists,
    write_to_session,
    _resolve_command,
)
from ...models import AISession as AISessionModel, ExternalIssue, Project, User
from ...services.activity_service import ActivityType, ResourceType, log_activity
from ...services.api_auth import require_api_auth
from ...services.tmux_service import session_name_for_user


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return slug or "session"


def _generate_tmux_target(session_name: str, project: Project, tool: str | None, issue_id: int | None) -> str:
    """Generate a tmux target for a project or issue.

    - With issue_id: reusable window per issue (e.g., aiops-p6-i713)
    - Without issue_id: unique window per session (e.g., aiops-p6-a1b2c3)
    """
    project_name = _slugify(getattr(project, "name", "") or "")
    project_id = getattr(project, "id", None)
    suffix = f"-p{project_id}" if project_id is not None else ""
    window_name = f"{project_name}{suffix}" if project_name else f"project{suffix}"
    if issue_id:
        window_name = f"{window_name}-i{issue_id}"
    else:
        # No issue - create unique window for each session
        window_name = f"{window_name}-{uuid.uuid4().hex[:6]}"
    return f"{session_name}:{window_name}"


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


def _get_project_session(project_id: int, session_id: str):
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return None, jsonify({"error": "Access denied."}), 403

    session = get_session(session_id)
    if session is None or session.project_id != project.id:
        return None, jsonify({"error": "Session not found."}), 404
    return session, None, None


@api_v1_bp.get("/projects/<int:project_id>/ai/sessions")
@require_api_auth(scopes=["read"])
def list_project_ai_sessions(project_id: int):
    """List active AI sessions for a project."""
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied."}), 403

    user_id = _current_user_id()

    # Import here to avoid circular imports
    from ...ai_sessions import list_active_sessions

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


@api_v1_bp.post("/projects/<int:project_id>/ai/sessions")
@require_api_auth(scopes=["write"])
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
    requested_user_id = data.get("user_id")  # Optional: admin can start session as another user
    permission_mode = data.get("permission_mode")  # Optional: override permission mode (e.g., "yolo")
    resolved_command = None

    current_app.logger.warning(f"DEBUG [API]: Received session request - tool={tool}, command={command}, issue_id={issue_id}")

    try:
        resolved_command = _resolve_command(tool, command, permission_mode=permission_mode)
        current_app.logger.warning(f"DEBUG [API]: Resolved command - tool={tool}, resolved_command={resolved_command}")
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
            from ...services.agent_context import write_tracked_issue_context
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
            from ...services.agent_context import write_global_context_only
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
                from ...ai_sessions import create_persistent_session
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
        "tool": getattr(session, "tool", None),  # Include tool info (useful when reattaching without --tool)
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


@api_v1_bp.post("/projects/<int:project_id>/ai/sessions/<session_id>/input")
@require_api_auth(scopes=["write"])
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


@api_v1_bp.post("/projects/<int:project_id>/ai/sessions/<session_id>/resize")
@require_api_auth(scopes=["write"])
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


@api_v1_bp.delete("/projects/<int:project_id>/ai/sessions/<session_id>")
@require_api_auth(scopes=["write"])
def stop_project_ai_session(project_id: int, session_id: str):
    session, error_response, status = _get_project_session(project_id, session_id)
    if error_response is not None:
        return error_response, status

    close_session(session)
    return ("", 204)


@api_v1_bp.get("/ai/sessions")
@require_api_auth(scopes=["read"])
def list_ai_sessions():
    """Get AI session history for the current user or all users (admin only)."""
    from ...services.ai_session_service import get_session_summary, get_user_sessions

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


@api_v1_bp.get("/ai/sessions/<int:db_session_id>/validate")
@require_api_auth(scopes=["read"])
def validate_ai_session(db_session_id: int):
    """Validate if a session's tmux target still exists and mark inactive if not."""
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
            from ...services.ai_session_service import end_session
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


@api_v1_bp.post("/ai/sessions/<int:db_session_id>/resume")
@require_api_auth(scopes=["write"])
def resume_ai_session(db_session_id: int):
    """Resume a previous AI session in its related tmux window."""
    from ...services.ai_session_service import build_resume_command

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


@api_v1_bp.post("/ai/sessions/<int:db_session_id>/attach")
@require_api_auth(scopes=["write"])
def track_session_attach(db_session_id: int):
    """Track when a user attaches to an existing session (CLI usage).

    This endpoint doesn't perform the attach operation itself (that's done via SSH+tmux),
    but logs the activity for tracking purposes.
    """
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
