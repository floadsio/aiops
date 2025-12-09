"""API v1 system management endpoints."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from flask import current_app, jsonify, request, send_file

from ...services.api_auth import audit_api_request, require_api_auth
from ...services.ai_cli_update_service import CLICommandError, run_ai_tool_update
from ...services.backup_service import (
    BackupError,
    create_backup,
    get_backup,
    list_backups,
    restore_backup,
)
from . import api_v1_bp


AI_TOOL_LABELS = {
    "codex": "Codex CLI",
    "claude": "Claude CLI",
}

AI_TOOL_SOURCES = {"npm", "brew"}


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


@api_v1_bp.post("/system/ai-tools/<tool>/update")
@require_api_auth(scopes=["admin"])
@audit_api_request
def update_ai_tool_cli(tool: str):
    """Run configured update command for supported AI tool CLIs.

    Request body:
        source: Required update source ("npm" or "brew")

    Returns:
        200 when the command finishes (success or failure)
        400 when the request is invalid or prerequisites are missing
        404 when the tool is unknown
    """
    data = request.get_json(silent=True) or {}
    source = (data.get("source") or "").strip().lower()
    normalized_tool = tool.lower().strip()

    if not source:
        return (
            jsonify({
                "error": "source is required (npm or brew)",
            }),
            400,
        )

    if source not in AI_TOOL_SOURCES:
        return (
            jsonify({
                "error": "Unsupported source. Use one of: npm, brew.",
            }),
            400,
        )

    tool_label = AI_TOOL_LABELS.get(normalized_tool)
    if not tool_label:
        return (
            jsonify({
                "error": f"Unsupported AI tool '{tool}'.",
            }),
            404,
        )

    try:
        result = run_ai_tool_update(normalized_tool, source)
    except CLICommandError as exc:
        return jsonify({"error": str(exc)}), 400

    payload = {
        "tool": normalized_tool,
        "tool_label": tool_label,
        "source": source,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "success": result.ok,
    }

    if result.ok:
        message = f"{tool_label} {source.upper()} command succeeded."
    else:
        message = f"{tool_label} {source.upper()} command failed."
        if result.stderr:
            message += f" Error: {result.stderr.strip()}"

    return jsonify({
        "success": result.ok,
        "message": message,
        "result": payload,
    })


@api_v1_bp.post("/system/backups")
@require_api_auth(scopes=["admin"])
@audit_api_request
def create_system_backup():
    """Create a new database backup.

    Request body:
        description (str, optional): Optional description of the backup

    Returns:
        201: Backup created successfully
        500: Backup creation failed
    """
    data = request.get_json(silent=True) or {}
    description = data.get("description")

    # Get user ID from API auth context if available
    user_id = getattr(request, "api_user_id", None)

    try:
        backup = create_backup(description=description, user_id=user_id)
        return jsonify({
            "message": "Backup created successfully",
            "backup": {
                "id": backup.id,
                "filename": backup.filename,
                "size_bytes": backup.size_bytes,
                "description": backup.description,
                "created_at": backup.created_at.isoformat() if backup.created_at else None,
            },
        }), 201
    except BackupError as exc:
        current_app.logger.error(f"Backup creation failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@api_v1_bp.get("/system/status")
@require_api_auth(scopes=["read"])
@audit_api_request
def get_system_status():
    """Get comprehensive system status for all components.

    Returns:
        200: System status with component health checks
    """
    try:
        from ...services.system_status import get_system_status as get_status
        status = get_status()
        return jsonify(status)
    except Exception as exc:
        current_app.logger.error(f"Failed to get system status: {exc}")
        return jsonify({"error": str(exc)}), 500


@api_v1_bp.get("/system/backups")
@require_api_auth(scopes=["admin"])
@audit_api_request
def list_system_backups():
    """List all available backups.

    Returns:
        200: List of backups
    """
    try:
        backups = list_backups()
        return jsonify({
            "backups": backups,
            "count": len(backups),
        })
    except Exception as exc:
        current_app.logger.error(f"Failed to list backups: {exc}")
        return jsonify({"error": str(exc)}), 500


@api_v1_bp.get("/system/backups/<int:backup_id>")
@require_api_auth(scopes=["admin"])
@audit_api_request
def get_system_backup(backup_id: int):
    """Get details of a specific backup.

    Args:
        backup_id: ID of the backup

    Returns:
        200: Backup details
        404: Backup not found
    """
    try:
        backup = get_backup(backup_id)
        return jsonify({
            "backup": {
                "id": backup.id,
                "filename": backup.filename,
                "filepath": backup.filepath,
                "size_bytes": backup.size_bytes,
                "description": backup.description,
                "created_at": backup.created_at.isoformat() if backup.created_at else None,
                "created_by": {
                    "id": backup.created_by.id,
                    "name": backup.created_by.name,
                    "email": backup.created_by.email,
                }
                if backup.created_by
                else None,
            },
        })
    except BackupError as exc:
        return jsonify({"error": str(exc)}), 404


@api_v1_bp.get("/system/backups/<int:backup_id>/download")
@require_api_auth(scopes=["admin"])
@audit_api_request
def download_system_backup(backup_id: int):
    """Download a backup file.

    Args:
        backup_id: ID of the backup

    Returns:
        200: Backup file download
        404: Backup not found
    """
    try:
        backup = get_backup(backup_id)
        backup_path = Path(backup.filepath)

        return send_file(
            backup_path,
            as_attachment=True,
            download_name=backup.filename,
            mimetype="application/gzip",
        )
    except BackupError as exc:
        return jsonify({"error": str(exc)}), 404


@api_v1_bp.post("/system/backups/<int:backup_id>/restore")
@require_api_auth(scopes=["admin"])
@audit_api_request
def restore_system_backup(backup_id: int):
    """Restore the database from a backup.

    This is a destructive operation that will replace the current database.

    Args:
        backup_id: ID of the backup to restore

    Returns:
        200: Restore successful
        404: Backup not found
        500: Restore failed
    """
    try:
        restore_backup(backup_id)
        return jsonify({
            "message": "Database restored successfully. Please restart the application.",
        })
    except BackupError as exc:
        current_app.logger.error(f"Backup restore failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@api_v1_bp.delete("/system/backups/<int:backup_id>")
@require_api_auth(scopes=["admin"])
@audit_api_request
def delete_system_backup(backup_id: int):
    """Delete a backup.

    Args:
        backup_id: ID of the backup to delete

    Returns:
        200: Backup deleted successfully
        404: Backup not found
        500: Delete failed
    """
    import os
    from ...extensions import db

    try:
        backup = get_backup(backup_id)
        filename = backup.filename

        # Delete the backup file
        if os.path.exists(backup.filepath):
            os.remove(backup.filepath)

        # Delete the database record
        db.session.delete(backup)
        db.session.commit()

        return jsonify({
            "message": f"Backup {filename} deleted successfully",
            "backup_id": backup_id,
        })
    except BackupError as exc:
        current_app.logger.error(f"Backup delete failed: {exc}")
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        current_app.logger.error(f"Backup delete failed: {exc}")
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500


# ============================================================================
# SSH KEYS API ENDPOINTS
# ============================================================================


@api_v1_bp.get("/admin/ssh-keys")
@require_api_auth(scopes=["admin"])
@audit_api_request
def list_ssh_keys():
    """List all SSH keys.

    Query params:
        tenant_id: Filter by tenant ID (optional)

    Returns:
        200: List of SSH keys with metadata
    """
    from ...models import SSHKey, Tenant
    from ...extensions import db

    tenant_id = request.args.get("tenant_id", type=int)

    query = db.session.query(SSHKey)
    if tenant_id:
        query = query.filter(SSHKey.tenant_id == tenant_id)

    keys = query.all()

    result = []
    for key in keys:
        tenant = db.session.get(Tenant, key.tenant_id) if key.tenant_id else None
        result.append({
            "id": key.id,
            "name": key.name,
            "tenant_id": key.tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "public_key": key.public_key,
            "private_key_path": key.private_key_path,
            "encrypted_private_key": bool(key.encrypted_private_key),
            "created_at": key.created_at.isoformat() if key.created_at else None,
        })

    return jsonify({"ssh_keys": result})


@api_v1_bp.post("/admin/ssh-keys")
@require_api_auth(scopes=["admin"])
@audit_api_request
def create_ssh_key():
    """Create a new SSH key with encrypted private key storage.

    Request body:
        name: Key name
        tenant_id: Tenant ID
        private_key_content: Private key content (will be encrypted)
        public_key_content: Public key content (optional)

    Returns:
        201: SSH key created
        400: Invalid request
        500: Encryption failed
    """
    from ...models import SSHKey
    from ...extensions import db
    from ...services.ssh_key_service import encrypt_private_key, SSHKeyServiceError

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    name = data.get("name")
    tenant_id = data.get("tenant_id")
    private_key_content = data.get("private_key_content")
    public_key_content = data.get("public_key_content")

    if not name or not tenant_id or not private_key_content:
        return jsonify({"error": "name, tenant_id, and private_key_content are required"}), 400

    try:
        # Encrypt private key
        encrypted_key = encrypt_private_key(private_key_content)

        # Create SSH key model
        ssh_key = SSHKey(
            name=name,
            tenant_id=tenant_id,
            public_key=public_key_content,
            encrypted_private_key=encrypted_key,
        )

        db.session.add(ssh_key)
        db.session.commit()

        return jsonify({
            "id": ssh_key.id,
            "name": ssh_key.name,
            "message": "SSH key created and encrypted successfully",
        }), 201

    except SSHKeyServiceError as exc:
        db.session.rollback()
        current_app.logger.error(f"Failed to encrypt SSH key: {exc}")
        return jsonify({"error": f"Encryption failed: {exc}"}), 500
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"Failed to create SSH key: {exc}")
        return jsonify({"error": str(exc)}), 500


@api_v1_bp.delete("/admin/ssh-keys/<int:key_id>")
@require_api_auth(scopes=["admin"])
@audit_api_request
def delete_ssh_key(key_id: int):
    """Delete an SSH key from the database.

    Args:
        key_id: SSH key ID

    Returns:
        200: SSH key deleted
        404: SSH key not found
    """
    from ...models import SSHKey
    from ...extensions import db

    ssh_key = db.session.get(SSHKey, key_id)
    if not ssh_key:
        return jsonify({"error": "SSH key not found"}), 404

    db.session.delete(ssh_key)
    db.session.commit()

    return jsonify({"message": f"SSH key {key_id} deleted successfully"})


@api_v1_bp.post("/admin/ssh-keys/<int:key_id>/migrate")
@require_api_auth(scopes=["admin"])
@audit_api_request
def migrate_ssh_key(key_id: int):
    """Migrate a filesystem SSH key to encrypted database storage.

    Args:
        key_id: SSH key ID

    Request body:
        private_key_content: Private key content from filesystem

    Returns:
        200: SSH key migrated
        404: SSH key not found
        400: Invalid request
        500: Migration failed
    """
    from ...models import SSHKey
    from ...extensions import db
    from ...services.ssh_key_service import encrypt_private_key, SSHKeyServiceError

    ssh_key = db.session.get(SSHKey, key_id)
    if not ssh_key:
        return jsonify({"error": "SSH key not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    private_key_content = data.get("private_key_content")
    if not private_key_content:
        return jsonify({"error": "private_key_content is required"}), 400

    try:
        # Encrypt private key
        encrypted_key = encrypt_private_key(private_key_content)

        # Update SSH key model
        ssh_key.encrypted_private_key = encrypted_key
        db.session.commit()

        return jsonify({
            "message": f"SSH key '{ssh_key.name}' migrated to database storage successfully",
        })

    except SSHKeyServiceError as exc:
        db.session.rollback()
        current_app.logger.error(f"Failed to encrypt SSH key: {exc}")
        return jsonify({"error": f"Encryption failed: {exc}"}), 500
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"Failed to migrate SSH key: {exc}")
        return jsonify({"error": str(exc)}), 500


@api_v1_bp.get("/system/sync/status")
@require_api_auth(scopes=["read"])
def get_sync_status():
    """Get automatic issue sync scheduler status.

    Returns:
        200: Sync scheduler status
    """
    from ...services.sync_scheduler import get_scheduler_status

    status = get_scheduler_status()

    # Add configuration info
    status["config"] = {
        "enabled": current_app.config.get("ISSUE_SYNC_ENABLED", False),
        "interval_seconds": current_app.config.get("ISSUE_SYNC_INTERVAL", 900),
        "sync_on_startup": current_app.config.get("ISSUE_SYNC_ON_STARTUP", True),
        "max_concurrent": current_app.config.get("ISSUE_SYNC_MAX_CONCURRENT", 3),
    }

    return jsonify(status)


@api_v1_bp.post("/system/sync/trigger")
@require_api_auth(scopes=["admin"])
@audit_api_request
def trigger_sync():
    """Manually trigger an immediate issue sync.

    Requires admin scope.

    Returns:
        200: Sync triggered
    """
    from ...services.sync_scheduler import trigger_sync_now

    trigger_sync_now(current_app._get_current_object())

    return jsonify({
        "message": "Issue sync triggered. Check logs for progress.",
    })


@api_v1_bp.get("/system/sync/history")
@require_api_auth(scopes=["read"])
def get_sync_history():
    """Get recent sync history.

    Query params:
        limit: Max number of records (default: 50, max: 200)
        project_integration_id: Filter by project integration

    Returns:
        200: List of sync history records
    """
    from ...models import SyncHistory, ProjectIntegration, Project
    from ...extensions import db

    limit = min(request.args.get("limit", 50, type=int), 200)
    pi_id = request.args.get("project_integration_id", type=int)

    query = (
        db.session.query(SyncHistory)
        .join(ProjectIntegration)
        .join(Project)
        .order_by(SyncHistory.created_at.desc())
    )

    if pi_id:
        query = query.filter(SyncHistory.project_integration_id == pi_id)

    records = query.limit(limit).all()

    result = []
    for record in records:
        pi = record.project_integration
        result.append({
            **record.to_dict(),
            "project_name": pi.project.name if pi and pi.project else None,
            "integration_name": pi.integration.name if pi and pi.integration else None,
        })

    return jsonify({
        "history": result,
        "count": len(result),
    })


@api_v1_bp.route("/system/switch-branch", methods=["POST"])
@require_api_auth(scopes=["admin"])
def switch_branch():
    """Switch the aiops backend to a specific git branch.

    This endpoint allows switching the production backend to a different branch
    for testing feature branches. It optionally restarts the service.

    Request body:
        branch (str): Git branch name to switch to
        restart (bool): Whether to restart the service after switching (default: true)

    Returns:
        JSON response with:
            - success: Whether the operation succeeded
            - current_branch: The current branch after switching
            - git_output: Output from git commands
            - restarted: Whether the service was restarted
    """
    audit_api_request("POST", "/api/v1/system/switch-branch")

    data = request.get_json() or {}
    branch = data.get("branch", "").strip()
    restart_service = data.get("restart", True)

    if not branch:
        return jsonify({"error": "branch is required"}), 400

    # Get the production aiops path
    prod_path = Path("/home/syseng/aiops")
    if not prod_path.exists():
        return jsonify({"error": "Production path /home/syseng/aiops not found"}), 404

    try:
        # Fetch latest from remote
        fetch_result = subprocess.run(
            ["sudo", "-u", "syseng", "git", "-C", str(prod_path), "fetch", "--all"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if fetch_result.returncode != 0:
            return jsonify({
                "success": False,
                "error": f"Git fetch failed: {fetch_result.stderr}",
            }), 500

        # Checkout the specified branch
        checkout_result = subprocess.run(
            ["sudo", "-u", "syseng", "git", "-C", str(prod_path), "checkout", branch],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if checkout_result.returncode != 0:
            return jsonify({
                "success": False,
                "error": f"Git checkout failed: {checkout_result.stderr}",
            }), 500

        # Pull latest changes for the branch
        pull_result = subprocess.run(
            ["sudo", "-u", "syseng", "git", "-C", str(prod_path), "pull"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        # Get current branch name
        branch_result = subprocess.run(
            ["sudo", "-u", "syseng", "git", "-C", str(prod_path), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        current_branch = branch_result.stdout.strip()

        # Combine git output
        git_output = (
            f"Fetch: {fetch_result.stdout}\n"
            f"Checkout: {checkout_result.stdout}\n"
            f"Pull: {pull_result.stdout}"
        ).strip()

        response = {
            "success": True,
            "current_branch": current_branch,
            "git_output": git_output,
            "restarted": False,
        }

        # Restart service if requested
        if restart_service:
            def restart_in_background():
                time.sleep(1)  # Give time to return response
                try:
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "aiops"],
                        check=True,
                        timeout=10,
                    )
                except Exception as e:
                    current_app.logger.error(f"Failed to restart service: {e}")

            thread = threading.Thread(target=restart_in_background, daemon=True)
            thread.start()
            response["restarted"] = True

        return jsonify(response)

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "Git operation timed out",
        }), 500
    except Exception as e:
        current_app.logger.exception("Failed to switch branch")
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500
