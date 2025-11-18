"""System status monitoring service for aiops core components."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy import text

from ..extensions import db


def check_database() -> dict[str, Any]:
    """Check database connectivity and health.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        # Test database connection with a simple query
        result = db.session.execute(text("SELECT 1")).scalar()
        if result == 1:
            # Get database file info
            db_path = current_app.config.get("SQLALCHEMY_DATABASE_URI", "").replace("sqlite:///", "")
            if db_path and Path(db_path).exists():
                size_mb = Path(db_path).stat().st_size / (1024 * 1024)
                return {
                    "healthy": True,
                    "message": "Database connected",
                    "details": {
                        "path": db_path,
                        "size_mb": round(size_mb, 2),
                    }
                }
            return {"healthy": True, "message": "Database connected"}
        return {"healthy": False, "message": "Database query failed"}
    except Exception as exc:  # noqa: BLE001
        return {
            "healthy": False,
            "message": f"Database error: {exc}",
            "details": {"error": str(exc)}
        }


def check_tmux_server() -> dict[str, Any]:
    """Check if tmux server is running.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            sessions = [s for s in result.stdout.strip().split("\n") if s]
            return {
                "healthy": True,
                "message": f"Tmux server running with {len(sessions)} session(s)",
                "details": {"session_count": len(sessions)}
            }
        # No sessions but server might be running
        if "no server running" in result.stderr:
            return {
                "healthy": True,
                "message": "Tmux server available (no sessions)",
                "details": {"session_count": 0}
            }
        return {
            "healthy": False,
            "message": "Tmux server not responding",
            "details": {"stderr": result.stderr}
        }
    except subprocess.TimeoutExpired:
        return {"healthy": False, "message": "Tmux server timeout"}
    except FileNotFoundError:
        return {"healthy": False, "message": "Tmux not installed"}
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Tmux error: {exc}"}


def check_git() -> dict[str, Any]:
    """Check if git is available.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return {
                "healthy": True,
                "message": "Git available",
                "details": {"version": version}
            }
        return {"healthy": False, "message": "Git command failed"}
    except FileNotFoundError:
        return {"healthy": False, "message": "Git not installed"}
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Git error: {exc}"}


def check_ai_tools() -> dict[str, Any]:
    """Check availability of AI tools (Claude, Codex, Gemini).

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    tools_config = current_app.config.get("ALLOWED_AI_TOOLS", {})
    tools_status = {}

    for tool_name, tool_command in tools_config.items():
        if tool_name == "shell":
            continue  # Skip shell check

        # Extract binary name from command
        binary = tool_command.split()[0] if tool_command else tool_name

        if shutil.which(binary):
            tools_status[tool_name] = {"available": True, "path": shutil.which(binary)}
        else:
            tools_status[tool_name] = {"available": False, "path": None}

    available_count = sum(1 for t in tools_status.values() if t["available"])
    total_count = len(tools_status)

    return {
        "healthy": available_count > 0,
        "message": f"{available_count}/{total_count} AI tools available",
        "details": {"tools": tools_status}
    }


def check_workspaces() -> dict[str, Any]:
    """Check workspace directory accessibility.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        instance_path = Path(current_app.instance_path)

        # Check instance directory
        if not instance_path.exists():
            return {
                "healthy": False,
                "message": "Instance directory missing",
                "details": {"path": str(instance_path)}
            }

        # Check workspace directories
        workspace_dirs = list(instance_path.glob("workspaces/*"))

        # Check session pipes
        pipes_dir = instance_path / "session_pipes"
        pipes_exist = pipes_dir.exists()
        pipe_count = len(list(pipes_dir.glob("*.log"))) if pipes_exist else 0

        return {
            "healthy": True,
            "message": "Workspace accessible",
            "details": {
                "instance_path": str(instance_path),
                "workspace_count": len(workspace_dirs),
                "session_pipes": pipe_count,
            }
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Workspace error: {exc}"}


def check_integrations() -> dict[str, Any]:
    """Check issue tracker integrations status.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        from ..models import IssueIntegration

        integrations = IssueIntegration.query.all()

        if not integrations:
            return {
                "healthy": True,
                "message": "No integrations configured",
                "details": {"count": 0}
            }

        integration_status = {}
        for integration in integrations:
            integration_status[integration.name] = {
                "provider": integration.provider,
                "enabled": integration.enabled,
            }

        enabled_count = sum(1 for i in integrations if i.enabled)

        return {
            "healthy": True,
            "message": f"{enabled_count}/{len(integrations)} integrations enabled",
            "details": {"integrations": integration_status}
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Integration check error: {exc}"}


def check_sessions() -> dict[str, Any]:
    """Check active AI sessions.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        from ..models import AISession as AISessionModel

        active_sessions = AISessionModel.query.filter_by(is_active=True).all()

        session_details = {
            "total_active": len(active_sessions),
            "by_tool": {},
        }

        for session in active_sessions:
            tool = session.tool or "unknown"
            session_details["by_tool"][tool] = session_details["by_tool"].get(tool, 0) + 1

        return {
            "healthy": True,
            "message": f"{len(active_sessions)} active session(s)",
            "details": session_details
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Session check error: {exc}"}


def get_system_status() -> dict[str, Any]:
    """Get comprehensive system status for all components.

    Returns:
        Dictionary with overall status and individual component statuses
    """
    components = {
        "database": check_database(),
        "tmux": check_tmux_server(),
        "git": check_git(),
        "ai_tools": check_ai_tools(),
        "workspaces": check_workspaces(),
        "integrations": check_integrations(),
        "sessions": check_sessions(),
    }

    # Calculate overall health
    all_healthy = all(comp.get("healthy", False) for comp in components.values())
    unhealthy_count = sum(1 for comp in components.values() if not comp.get("healthy", False))

    return {
        "healthy": all_healthy,
        "timestamp": datetime.utcnow().isoformat(),
        "components": components,
        "summary": {
            "total_components": len(components),
            "healthy_components": len(components) - unhealthy_count,
            "unhealthy_components": unhealthy_count,
        }
    }
