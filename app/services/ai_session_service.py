"""Service for persisting and managing AI tool sessions for resumption."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

from flask import current_app

from ..extensions import db
from ..models import AISession, Project, User

# Regex patterns to extract session IDs from tool output
SESSION_ID_PATTERNS = {
    "claude": re.compile(
        r"(?:To continue this session, run|Resume with:|session ID:?)\s+(?:claude\s+(?:--resume|resume)\s+)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        re.IGNORECASE,
    ),
    "codex": re.compile(
        r"(?:To continue this session, run|Resume with:|session ID:?)\s+(?:codex\s+resume\s+)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        re.IGNORECASE,
    ),
    "gemini": re.compile(
        r"(?:Session saved as|Resume with:|/chat resume)\s+['\"]?([a-zA-Z0-9_-]+)['\"]?",
        re.IGNORECASE,
    ),
}


def detect_session_id(tool: str, output: str) -> Optional[str]:
    """Detect and extract session ID from tool output.

    Args:
        tool: The AI tool name (claude, codex, gemini)
        output: The text output from the tool

    Returns:
        The extracted session ID, or None if not found
    """
    pattern = SESSION_ID_PATTERNS.get(tool)
    if not pattern:
        return None

    match = pattern.search(output)
    if match:
        return match.group(1)
    return None


def save_session(
    project_id: int,
    user_id: int,
    tool: str,
    session_id: str,
    command: Optional[str] = None,
    description: Optional[str] = None,
    tmux_target: Optional[str] = None,
    issue_id: Optional[int] = None,
) -> AISession:
    """Save a new AI session to the database.

    Args:
        project_id: The project ID
        user_id: The user ID
        tool: The AI tool name (claude, codex, gemini)
        session_id: The tool's session identifier
        command: The command that was run
        description: Optional description of the session
        tmux_target: Optional tmux window/pane target
        issue_id: Optional issue ID if this session is for an issue

    Returns:
        The created AISession database record
    """
    session = AISession(
        project_id=project_id,
        user_id=user_id,
        tool=tool,
        session_id=session_id,
        command=command,
        description=description,
        tmux_target=tmux_target,
        issue_id=issue_id,
        started_at=datetime.utcnow(),
        is_active=True,
    )
    db.session.add(session)
    db.session.commit()

    current_app.logger.info(
        "Saved %s session %s for user %s in project %s",
        tool,
        session_id,
        user_id,
        project_id,
    )
    return session


def end_session(session_id: int) -> None:
    """Mark a session as ended.

    Args:
        session_id: The database ID of the AISession record
    """
    session = AISession.query.get(session_id)
    if session:
        session.is_active = False
        session.ended_at = datetime.utcnow()
        db.session.commit()


def get_user_sessions(
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
    tool: Optional[str] = None,
    active_only: bool = True,
) -> list[AISession]:
    """Get AI sessions for a user or all users.

    Args:
        user_id: The user ID (None to fetch all users' sessions)
        project_id: Optional project ID filter
        tool: Optional tool name filter (claude, codex, gemini)
        active_only: Only return active sessions

    Returns:
        List of AISession records matching the criteria
    """
    query = AISession.query

    if user_id is not None:
        query = query.filter_by(user_id=user_id)

    if project_id is not None:
        query = query.filter_by(project_id=project_id)

    if tool is not None:
        query = query.filter_by(tool=tool)

    if active_only:
        query = query.filter_by(is_active=True)

    return query.order_by(AISession.started_at.desc()).all()


def build_resume_command(session: AISession) -> str:
    """Build the command to resume a session.

    Args:
        session: The AISession database record

    Returns:
        The command string to resume the session
    """
    tool = session.tool
    session_id = session.session_id

    if tool == "claude":
        return f"claude --resume {session_id}"
    elif tool == "codex":
        return f"codex resume {session_id}"
    elif tool == "gemini":
        return f"gemini  # Then use: /chat resume {session_id}"
    else:
        return f"{tool} resume {session_id}"


def get_session_summary(session: AISession) -> dict:
    """Get a summary of a session for display.

    Args:
        session: The AISession database record

    Returns:
        Dictionary with session summary information
    """
    from ..services.git_service import ensure_repo_checkout

    project = Project.query.get(session.project_id)
    user = User.query.get(session.user_id)

    # Try to get branch information
    branch = None
    if project:
        try:
            repo = ensure_repo_checkout(project)
            if repo and repo.head.is_detached is False:
                branch = repo.active_branch.name
        except Exception:  # noqa: BLE001
            pass

    elapsed = None
    if session.ended_at:
        elapsed = (session.ended_at - session.started_at).total_seconds()
    else:
        elapsed = (datetime.utcnow() - session.started_at).total_seconds()

    # Check if pane is dead
    pane_dead = False
    linux_username = user.linux_username if user else None
    if session.tmux_target and session.is_active:
        from ..services.tmux_service import is_pane_dead
        pane_dead = is_pane_dead(session.tmux_target, linux_username=linux_username)

    # Get tmux server owner and socket path
    # Per-user sessions run in user's own tmux server
    from ..services.tmux_service import get_user_socket_path

    if linux_username and linux_username != "syseng":
        tmux_server_user = linux_username
        socket_path = get_user_socket_path(linux_username)
        attach_command = f"tmux -S {socket_path} attach -t {session.tmux_target}"
    else:
        import pwd
        tmux_server_user = pwd.getpwuid(os.getuid()).pw_name
        socket_path = None
        attach_command = f"tmux attach -t {session.tmux_target}" if session.tmux_target else None

    return {
        "id": session.id,
        "tool": session.tool,
        "session_id": session.session_id,
        "project_id": session.project_id,
        "project_name": project.name if project else "Unknown",
        "tenant_name": project.tenant.name if project and project.tenant else "Unknown",
        "user_id": session.user_id,
        "user_name": user.name if user else "Unknown",
        "linux_username": linux_username,
        "tmux_server_user": tmux_server_user,
        "socket_path": socket_path,
        "attach_command": attach_command,
        "issue_id": session.issue_id,
        "description": session.description,
        "command": session.command,
        "tmux_target": session.tmux_target,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "is_active": session.is_active,
        "elapsed_seconds": int(elapsed),
        "branch": branch,
        "resume_command": build_resume_command(session),
        "pane_dead": pane_dead,
    }


def cleanup_stale_sessions(restart_tmux: bool = False) -> dict[str, int]:
    """Mark all active sessions as inactive and optionally restart tmux servers.

    This is a maintenance function that:
    1. Optionally kills all tmux servers (if restart_tmux=True)
    2. Marks all active AI sessions as inactive
    3. Returns counts of affected sessions

    Args:
        restart_tmux: If True, kills all tmux servers before cleaning up sessions

    Returns:
        Dictionary with counts of marked_inactive sessions and tmux_restarted flag
    """
    import subprocess

    tmux_restarted = False

    # Optionally restart tmux by killing all servers
    if restart_tmux:
        try:
            # Kill all tmux servers for all users
            # This is safe because tmux will auto-restart when needed
            subprocess.run(
                ["pkill", "-9", "tmux"],
                capture_output=True,
                timeout=5,
            )
            current_app.logger.info("Killed all tmux servers for cleanup")
            tmux_restarted = True
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(f"Failed to kill tmux servers: {exc}")

    # Get all active sessions and mark them as inactive
    active_sessions = AISession.query.filter_by(is_active=True).all()
    marked_inactive = len(active_sessions)

    for session in active_sessions:
        session.is_active = False
        session.ended_at = datetime.utcnow()

    if marked_inactive > 0:
        db.session.commit()
        current_app.logger.info(f"Cleanup: marked {marked_inactive} sessions as inactive")

    return {
        "marked_inactive": marked_inactive,
        "total_checked": len(active_sessions),
        "tmux_restarted": tmux_restarted,
    }
