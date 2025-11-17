"""API v1 system management endpoints."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from flask import current_app, jsonify, request

from ...services.api_auth import audit_api_request, require_api_auth
from . import api_v1_bp


def _run_git_pull(repo_path: Path) -> dict[str, str]:
    """Run git pull in the repository.

    Args:
        repo_path: Path to the repository

    Returns:
        dict with stdout and stderr
    """
    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": True,
        }
    except subprocess.CalledProcessError as exc:
        return {
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "success": False,
            "error": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Git pull timed out after 60 seconds",
            "success": False,
            "error": "Timeout",
        }


def _run_uv_sync(repo_path: Path) -> dict[str, str]:
    """Run uv pip sync to install dependencies.

    Args:
        repo_path: Path to the repository

    Returns:
        dict with stdout and stderr
    """
    venv_dir = repo_path / ".venv"
    requirements_file = repo_path / "requirements.txt"

    if not requirements_file.exists():
        return {
            "stdout": "",
            "stderr": "requirements.txt not found",
            "success": False,
            "error": "Missing requirements.txt",
        }

    try:
        result = subprocess.run(
            ["uv", "pip", "sync", "--python", str(venv_dir), str(requirements_file)],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes
            check=True,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": True,
        }
    except subprocess.CalledProcessError as exc:
        return {
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "success": False,
            "error": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "uv pip sync timed out after 5 minutes",
            "success": False,
            "error": "Timeout",
        }


def _run_flask_migrations(repo_path: Path) -> dict[str, str]:
    """Run Flask database migrations.

    Args:
        repo_path: Path to the repository

    Returns:
        dict with stdout and stderr
    """
    venv_python = repo_path / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return {
            "stdout": "",
            "stderr": "Virtual environment not found",
            "success": False,
            "error": "No venv",
        }

    try:
        result = subprocess.run(
            [str(venv_python), "-m", "flask", "--app", "manage.py", "db", "upgrade"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": True,
        }
    except subprocess.CalledProcessError as exc:
        return {
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "success": False,
            "error": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Database migration timed out after 60 seconds",
            "success": False,
            "error": "Timeout",
        }


def _restart_flask_service() -> dict[str, str]:
    """Restart the Flask application service.

    This attempts to restart the systemd service if running under systemd,
    otherwise it exits the process (assuming it's managed by a process manager).

    Returns:
        dict with result information
    """
    # Check if running under systemd
    service_name = os.getenv("SYSTEMD_SERVICE_NAME", "aiops")

    try:
        # Try to restart via systemd
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode == 0:
            return {
                "stdout": f"Service {service_name} restarted via systemd",
                "stderr": result.stderr,
                "success": True,
                "method": "systemd",
            }
        else:
            # Fallback: schedule process exit (process manager should restart)
            return {
                "stdout": "Scheduled process exit (process manager will restart)",
                "stderr": "systemd restart failed, falling back to exit",
                "success": True,
                "method": "exit",
            }
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # Fallback: schedule process exit
        return {
            "stdout": "Scheduled process exit (process manager will restart)",
            "stderr": "systemd not available, falling back to exit",
            "success": True,
            "method": "exit",
        }


@api_v1_bp.post("/system/update")
@require_api_auth(scopes=["admin"])
@audit_api_request
def update_system():
    """Update the aiops application code and dependencies.

    This endpoint:
    1. Runs git pull to fetch latest code
    2. Runs uv sync to update dependencies
    3. Runs database migrations

    Requires admin scope.

    Request body:
        skip_migrations (bool, optional): Skip database migrations (default: False)

    Returns:
        200: Update completed successfully
        500: Update failed
    """
    data = request.get_json(silent=True) or {}
    skip_migrations = data.get("skip_migrations", False)

    # Determine the aiops repository path
    # This should be the production instance, not the user's workspace
    aiops_root = Path(current_app.config.get("AIOPS_ROOT", "/home/syseng/aiops"))

    if not aiops_root.exists():
        return jsonify({
            "error": f"aiops root directory not found: {aiops_root}",
        }), 500

    results = {}

    # Step 1: Git pull
    current_app.logger.info("Running git pull in %s", aiops_root)
    git_result = _run_git_pull(aiops_root)
    results["git_pull"] = git_result

    if not git_result["success"]:
        return jsonify({
            "error": "Git pull failed",
            "results": results,
        }), 500

    # Step 2: UV sync
    current_app.logger.info("Running uv sync in %s", aiops_root)
    uv_result = _run_uv_sync(aiops_root)
    results["uv_sync"] = uv_result

    if not uv_result["success"]:
        return jsonify({
            "error": "Dependency installation failed",
            "results": results,
        }), 500

    # Step 3: Database migrations (unless skipped)
    if not skip_migrations:
        current_app.logger.info("Running database migrations in %s", aiops_root)
        migrate_result = _run_flask_migrations(aiops_root)
        results["migrations"] = migrate_result

        if not migrate_result["success"]:
            return jsonify({
                "error": "Database migration failed",
                "results": results,
            }), 500
    else:
        results["migrations"] = {"skipped": True}

    return jsonify({
        "message": "System updated successfully",
        "results": results,
    })


@api_v1_bp.post("/system/restart")
@require_api_auth(scopes=["admin"])
@audit_api_request
def restart_system():
    """Restart the aiops application.

    This endpoint attempts to restart the Flask application via systemd,
    or schedules a process exit if systemd is not available.

    Requires admin scope.

    Returns:
        200: Restart initiated successfully
        500: Restart failed
    """

    def delayed_restart():
        """Delayed restart to allow response to be sent."""
        time.sleep(2)  # Wait 2 seconds to allow response to be sent
        restart_result = _restart_flask_service()

        if restart_result.get("method") == "exit":
            current_app.logger.info("Exiting process for restart")
            os._exit(0)  # Force exit (process manager should restart)

    # Start restart in background thread
    restart_thread = threading.Thread(target=delayed_restart, daemon=True)
    restart_thread.start()

    return jsonify({
        "message": "Restart initiated. The application will restart in 2 seconds.",
    })


@api_v1_bp.post("/system/update-and-restart")
@require_api_auth(scopes=["admin"])
@audit_api_request
def update_and_restart_system():
    """Update and restart the aiops application.

    This endpoint combines update and restart operations:
    1. Runs git pull
    2. Updates dependencies
    3. Runs migrations
    4. Restarts the application

    Requires admin scope.

    Request body:
        skip_migrations (bool, optional): Skip database migrations (default: False)

    Returns:
        200: Update completed, restart initiated
        500: Update failed
    """
    data = request.get_json(silent=True) or {}
    skip_migrations = data.get("skip_migrations", False)

    # Determine the aiops repository path
    aiops_root = Path(current_app.config.get("AIOPS_ROOT", "/home/syseng/aiops"))

    if not aiops_root.exists():
        return jsonify({
            "error": f"aiops root directory not found: {aiops_root}",
        }), 500

    results = {}

    # Step 1: Git pull
    current_app.logger.info("Running git pull in %s", aiops_root)
    git_result = _run_git_pull(aiops_root)
    results["git_pull"] = git_result

    if not git_result["success"]:
        return jsonify({
            "error": "Git pull failed",
            "results": results,
        }), 500

    # Step 2: UV sync
    current_app.logger.info("Running uv sync in %s", aiops_root)
    uv_result = _run_uv_sync(aiops_root)
    results["uv_sync"] = uv_result

    if not uv_result["success"]:
        return jsonify({
            "error": "Dependency installation failed",
            "results": results,
        }), 500

    # Step 3: Database migrations (unless skipped)
    if not skip_migrations:
        current_app.logger.info("Running database migrations in %s", aiops_root)
        migrate_result = _run_flask_migrations(aiops_root)
        results["migrations"] = migrate_result

        if not migrate_result["success"]:
            return jsonify({
                "error": "Database migration failed",
                "results": results,
            }), 500
    else:
        results["migrations"] = {"skipped": True}

    # Step 4: Schedule restart
    def delayed_restart():
        """Delayed restart to allow response to be sent."""
        time.sleep(2)
        restart_result = _restart_flask_service()

        if restart_result.get("method") == "exit":
            current_app.logger.info("Exiting process for restart")
            os._exit(0)

    restart_thread = threading.Thread(target=delayed_restart, daemon=True)
    restart_thread.start()

    return jsonify({
        "message": "System updated successfully. Restart initiated.",
        "results": results,
    })
