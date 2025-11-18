"""Service for recovering tmux sessions after backend restart."""

from __future__ import annotations

import subprocess

from flask import current_app

from ..models import AISession as AISessionModel


def list_tmux_sessions() -> list[dict[str, str]]:
    """List all tmux sessions and windows.

    Returns:
        List of dicts with 'session_name', 'window_name', and 'tmux_target'
    """
    try:
        result = subprocess.run(
            ["tmux", "list-windows", "-a", "-F", "#{session_name}:#{window_name}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        sessions = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            if ":" in line:
                session_name, window_name = line.split(":", 1)
                sessions.append({
                    "session_name": session_name,
                    "window_name": window_name,
                    "tmux_target": line,
                })
        return sessions
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as exc:  # noqa: BLE001
        current_app.logger.warning("Failed to list tmux sessions: %s", exc)
        return []


def match_orphaned_sessions() -> list[tuple[AISessionModel, dict[str, str]]]:
    """Find database sessions that have matching tmux sessions.

    Returns:
        List of (AISessionModel, tmux_info) tuples for recoverable sessions
    """
    # Get all active sessions from database
    active_db_sessions = AISessionModel.query.filter_by(is_active=True).all()

    # Get all tmux sessions
    tmux_sessions = list_tmux_sessions()

    # Create lookup dict by tmux_target
    tmux_by_target = {s["tmux_target"]: s for s in tmux_sessions}

    # Match database sessions to tmux sessions
    matches = []
    for db_session in active_db_sessions:
        if db_session.tmux_target and db_session.tmux_target in tmux_by_target:
            tmux_info = tmux_by_target[db_session.tmux_target]
            matches.append((db_session, tmux_info))
            current_app.logger.info(
                "Found recoverable session: DB ID %s -> tmux %s",
                db_session.id,
                db_session.tmux_target,
            )

    return matches


def scan_and_log_orphaned_sessions() -> int:
    """Scan for orphaned tmux sessions and log them.

    This is called on backend startup to identify sessions that can be recovered.

    Returns:
        Number of recoverable sessions found
    """
    matches = match_orphaned_sessions()

    if matches:
        current_app.logger.info(
            "Found %d recoverable tmux session(s) after restart:", len(matches)
        )
        for db_session, tmux_info in matches:
            current_app.logger.info(
                "  - Session %s (user_id=%s, tool=%s) @ %s",
                db_session.session_id[:12],
                db_session.user_id,
                db_session.tool,
                tmux_info["tmux_target"],
            )
    else:
        current_app.logger.info("No recoverable tmux sessions found after restart")

    return len(matches)
