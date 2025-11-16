"""API v1 git repository operations endpoints."""

from __future__ import annotations


from flask import current_app, g, jsonify, request

from ...models import Project
from ...services.api_auth import audit_api_request, require_api_auth
from ...services.git_service import get_repo_status, run_git_action
from ...services.workspace_service import (
    WorkspaceError,
    get_workspace_path,
    get_workspace_status,
    initialize_workspace,
)
from . import api_v1_bp


def _ensure_project_access(project: Project) -> bool:
    """Check if current user has access to project."""
    user = g.api_user
    if user.is_admin:
        return True
    return project.owner_id == user.id


@api_v1_bp.post("/projects/<int:project_id>/git/pull")
@require_api_auth(scopes=["write"])
@audit_api_request
def git_pull(project_id: int):
    """Pull latest changes from remote repository.

    Args:
        project_id: Project ID

    Query params:
        ref (str, optional): Specific branch or ref to pull
        clean (bool): Clean working directory before pulling

    Returns:
        200: Pull output
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    ref = request.args.get("ref")
    clean = request.args.get("clean", "false").lower() == "true"
    user = g.api_user

    try:
        output = run_git_action(project, "pull", ref=ref, clean=clean, user=user)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    return jsonify({"result": output, "message": "Pull completed successfully"})


@api_v1_bp.post("/projects/<int:project_id>/git/push")
@require_api_auth(scopes=["write"])
@audit_api_request
def git_push(project_id: int):
    """Push local changes to remote repository.

    Args:
        project_id: Project ID

    Query params:
        ref (str, optional): Specific branch or ref to push

    Returns:
        200: Push output
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    ref = request.args.get("ref")
    user = g.api_user

    try:
        output = run_git_action(project, "push", ref=ref, user=user)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    return jsonify({"result": output, "message": "Push completed successfully"})


@api_v1_bp.get("/projects/<int:project_id>/git/status")
@require_api_auth(scopes=["read"])
@audit_api_request
def git_status(project_id: int):
    """Get git repository status.

    Args:
        project_id: Project ID

    Returns:
        200: Git status information
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user
    status = get_repo_status(project, user=user)
    return jsonify({"status": status})


@api_v1_bp.post("/projects/<int:project_id>/git/commit")
@require_api_auth(scopes=["write"])
@audit_api_request
def git_commit(project_id: int):
    """Commit changes to the repository.

    Args:
        project_id: Project ID

    Request body:
        message (str): Commit message (required)
        files (list[str], optional): Specific files to commit (defaults to all)

    Returns:
        200: Commit successful
        400: Invalid request
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    files = data.get("files", [])

    if not message:
        return jsonify({"error": "Commit message is required"}), 400

    try:
        workspace_path = get_workspace_path(project, user)
        from ...services.sudo_service import run_as_user
        from ...services.linux_users import resolve_linux_username

        linux_username = resolve_linux_username(user)

        # Add files to staging
        if files:
            for file_path in files:
                run_as_user(
                    linux_username,
                    ["git", "-C", str(workspace_path), "add", file_path],
                    timeout=10.0,
                )
        else:
            # Add all changes
            run_as_user(
                linux_username,
                ["git", "-C", str(workspace_path), "add", "-A"],
                timeout=10.0,
            )

        # Create commit
        result = run_as_user(
            linux_username,
            ["git", "-C", str(workspace_path), "commit", "-m", message],
            timeout=30.0,
        )

        return jsonify({
            "message": "Commit created successfully",
            "output": result.stdout,
        })
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to commit: %s", exc)
        return jsonify({"error": f"Failed to commit: {str(exc)}"}), 400


@api_v1_bp.get("/projects/<int:project_id>/git/branches")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_branches(project_id: int):
    """List all branches in the repository.

    Args:
        project_id: Project ID

    Returns:
        200: List of branches
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user

    try:
        workspace_path = get_workspace_path(project, user)
        from ...services.sudo_service import run_as_user
        from ...services.linux_users import resolve_linux_username

        linux_username = resolve_linux_username(user)

        # Get current branch
        current_result = run_as_user(
            linux_username,
            ["git", "-C", str(workspace_path), "branch", "--show-current"],
            timeout=5.0,
        )
        current_branch = current_result.stdout.strip()

        # Get all branches
        result = run_as_user(
            linux_username,
            ["git", "-C", str(workspace_path), "branch", "-a"],
            timeout=10.0,
        )

        branches = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line:
                continue
            is_current = line.startswith("*")
            branch_name = line.lstrip("* ").strip()
            if branch_name:
                branches.append({
                    "name": branch_name,
                    "is_current": is_current,
                })

        return jsonify({
            "branches": branches,
            "current_branch": current_branch,
        })
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to list branches: %s", exc)
        return jsonify({"error": f"Failed to list branches: {str(exc)}"}), 400


@api_v1_bp.post("/projects/<int:project_id>/git/branches")
@require_api_auth(scopes=["write"])
@audit_api_request
def create_branch(project_id: int):
    """Create a new branch.

    Args:
        project_id: Project ID

    Request body:
        name (str): Branch name (required)
        from_branch (str, optional): Create from this branch (defaults to current)
        checkout (bool): Whether to checkout the new branch (default: true)

    Returns:
        201: Branch created successfully
        400: Invalid request
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user
    data = request.get_json(silent=True) or {}
    branch_name = (data.get("name") or "").strip()
    from_branch = (data.get("from_branch") or "").strip()
    checkout = data.get("checkout", True)

    if not branch_name:
        return jsonify({"error": "Branch name is required"}), 400

    try:
        workspace_path = get_workspace_path(project, user)
        from ...services.sudo_service import run_as_user
        from ...services.linux_users import resolve_linux_username

        linux_username = resolve_linux_username(user)

        # Create branch
        cmd = ["git", "-C", str(workspace_path), "branch", branch_name]
        if from_branch:
            cmd.append(from_branch)

        run_as_user(linux_username, cmd, timeout=10.0)

        # Checkout if requested
        if checkout:
            run_as_user(
                linux_username,
                ["git", "-C", str(workspace_path), "checkout", branch_name],
                timeout=10.0,
            )

        return jsonify({
            "message": f"Branch '{branch_name}' created successfully",
            "branch": branch_name,
            "checked_out": checkout,
        }), 201
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to create branch: %s", exc)
        return jsonify({"error": f"Failed to create branch: {str(exc)}"}), 400


@api_v1_bp.post("/projects/<int:project_id>/git/checkout")
@require_api_auth(scopes=["write"])
@audit_api_request
def checkout_branch(project_id: int):
    """Switch to a different branch.

    Args:
        project_id: Project ID

    Request body:
        branch (str): Branch name to checkout (required)

    Returns:
        200: Branch switched successfully
        400: Invalid request
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user
    data = request.get_json(silent=True) or {}
    branch = (data.get("branch") or "").strip()

    if not branch:
        return jsonify({"error": "Branch name is required"}), 400

    try:
        workspace_path = get_workspace_path(project, user)
        from ...services.sudo_service import run_as_user
        from ...services.linux_users import resolve_linux_username

        linux_username = resolve_linux_username(user)

        run_as_user(
            linux_username,
            ["git", "-C", str(workspace_path), "checkout", branch],
            timeout=30.0,
        )

        return jsonify({
            "message": f"Switched to branch '{branch}'",
            "branch": branch,
        })
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to checkout branch: %s", exc)
        return jsonify({"error": f"Failed to checkout branch: {str(exc)}"}), 400


@api_v1_bp.get("/projects/<int:project_id>/files")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_files(project_id: int):
    """List files and directories in the repository.

    Args:
        project_id: Project ID

    Query params:
        path (str, optional): Subdirectory path (defaults to root)

    Returns:
        200: File listing
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user
    subpath = request.args.get("path", "").strip("/")

    try:
        workspace_path = get_workspace_path(project, user)
        target_path = workspace_path / subpath if subpath else workspace_path

        # Security check: ensure target_path is within workspace_path
        try:
            target_path.resolve().relative_to(workspace_path.resolve())
        except ValueError:
            return jsonify({"error": "Invalid path"}), 400

        from ...services.sudo_service import run_as_user
        from ...services.linux_users import resolve_linux_username

        linux_username = resolve_linux_username(user)

        # List directory contents
        result = run_as_user(
            linux_username,
            ["ls", "-la", str(target_path)],
            timeout=10.0,
        )

        files = []
        for line in result.stdout.split("\n")[1:]:  # Skip total line
            if not line.strip():
                continue
            parts = line.split(maxsplit=8)
            if len(parts) >= 9:
                name = parts[8]
                if name in (".", ".."):
                    continue
                is_dir = parts[0].startswith("d")
                files.append({
                    "name": name,
                    "is_directory": is_dir,
                    "permissions": parts[0],
                    "size": parts[4],
                })

        return jsonify({
            "path": subpath or "/",
            "files": files,
        })
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to list files: %s", exc)
        return jsonify({"error": f"Failed to list files: {str(exc)}"}), 400


@api_v1_bp.get("/projects/<int:project_id>/files/<path:file_path>")
@require_api_auth(scopes=["read"])
@audit_api_request
def read_file(project_id: int, file_path: str):
    """Read a file from the repository.

    Args:
        project_id: Project ID
        file_path: Path to file relative to repository root

    Returns:
        200: File contents
        403: Access denied
        404: Project or file not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user

    try:
        workspace_path = get_workspace_path(project, user)
        target_file = workspace_path / file_path

        # Security check: ensure target_file is within workspace_path
        try:
            target_file.resolve().relative_to(workspace_path.resolve())
        except ValueError:
            return jsonify({"error": "Invalid file path"}), 400

        from ...services.sudo_service import run_as_user
        from ...services.linux_users import resolve_linux_username

        linux_username = resolve_linux_username(user)

        # Read file
        result = run_as_user(
            linux_username,
            ["cat", str(target_file)],
            timeout=30.0,
        )

        return jsonify({
            "path": file_path,
            "content": result.stdout,
        })
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to read file: %s", exc)
        return jsonify({"error": f"Failed to read file: {str(exc)}"}), 404


@api_v1_bp.get("/projects/<int:project_id>/workspace/status")
@require_api_auth(scopes=["read"])
@audit_api_request
def workspace_status(project_id: int):
    """Get workspace status for the current user.

    Args:
        project_id: Project ID

    Returns:
        200: Workspace status
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user
    status = get_workspace_status(project, user)
    return jsonify({"workspace": status})


@api_v1_bp.post("/projects/<int:project_id>/workspace/init")
@require_api_auth(scopes=["write"])
@audit_api_request
def init_workspace(project_id: int):
    """Initialize workspace for the current user.

    Args:
        project_id: Project ID

    Returns:
        201: Workspace initialized
        400: Initialization failed
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    user = g.api_user

    try:
        workspace_path = initialize_workspace(project, user)
        return jsonify({
            "message": "Workspace initialized successfully",
            "path": str(workspace_path),
        }), 201
    except WorkspaceError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Failed to initialize workspace: {exc}"}), 500
