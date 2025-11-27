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


def reconnect_persistent_sessions() -> int:
    """Reconnect to persistent sessions after backend restart.

    This scans for active sessions in the database that have matching tmux
    sessions and recreates the in-memory session objects with output streaming.

    Returns:
        Number of sessions reconnected
    """
    if not current_app.config.get("ENABLE_PERSISTENT_SESSIONS", False):
        return 0

    from pathlib import Path
    from ..ai_sessions import PersistentAISession, _register_session, _pipe_reader_loop
    import threading

    matches = match_orphaned_sessions()
    reconnected = 0

    pipe_dir = Path(current_app.instance_path) / "session_pipes"
    pipe_dir.mkdir(parents=True, exist_ok=True)

    for db_session, tmux_info in matches:
        # Reconstruct pipe file path
        pipe_file = str(pipe_dir / f"{db_session.session_id}.log")

        # Create persistent session object
        session_obj = PersistentAISession(
            session_id=db_session.session_id,
            project_id=db_session.project_id,
            user_id=db_session.user_id,
            tool=db_session.tool,
            command=db_session.command or "",
            tmux_target=db_session.tmux_target,
            pipe_file=pipe_file,
            issue_id=db_session.issue_id,
        )

        # If pipe file exists, seek to end to only capture new output
        if Path(pipe_file).exists():
            session_obj._file_position = Path(pipe_file).stat().st_size

        # Register and start output streaming
        _register_session(session_obj)
        threading.Thread(target=_pipe_reader_loop, args=(session_obj,), daemon=True).start()

        reconnected += 1
        current_app.logger.info(
            "Reconnected persistent session %s @ %s",
            db_session.session_id[:12],
            tmux_info["tmux_target"],
        )

    if reconnected > 0:
        current_app.logger.info("Successfully reconnected %d persistent session(s)", reconnected)

    return reconnected
