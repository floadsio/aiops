"""API v1 git repository operations endpoints."""

from __future__ import annotations


from flask import current_app, g, jsonify, request

from ...models import Project
from ...services.activity_service import ActivityType, ResourceType, log_activity
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

        # Log activity
        user_agent = request.headers.get("User-Agent", "").lower()
        source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"
        log_activity(
            action_type=ActivityType.GIT_PULL,
            user_id=user.id,
            resource_type=ResourceType.PROJECT,
            resource_id=project.id,
            resource_name=project.name,
            status="success",
            description=f"Git pull on project {project.name}",
            source=source,
        )
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

        # Log activity
        user_agent = request.headers.get("User-Agent", "").lower()
        source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"
        log_activity(
            action_type=ActivityType.GIT_PUSH,
            user_id=user.id,
            resource_type=ResourceType.PROJECT,
            resource_id=project.id,
            resource_name=project.name,
            status="success",
            description=f"Git push on project {project.name}",
            source=source,
        )
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

        # Log activity
        user_agent = request.headers.get("User-Agent", "").lower()
        source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"
        log_activity(
            action_type=ActivityType.GIT_COMMIT,
            user_id=user.id,
            resource_type=ResourceType.PROJECT,
            resource_id=project.id,
            resource_name=project.name,
            status="success",
            description=f"Git commit on project {project.name}: {message[:50]}",
            source=source,
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


@api_v1_bp.post("/projects/<int:project_id>/pull-requests")
@require_api_auth(scopes=["write"])
@audit_api_request
def create_pull_request(project_id: int):
    """Create a pull request (GitHub) or merge request (GitLab).

    Args:
        project_id: Project ID

    Request body:
        title (str): PR/MR title (required)
        description (str): PR/MR description
        source_branch (str): Source branch name (required)
        target_branch (str): Target branch name (default: main)
        assignee (str): Username to assign as reviewer (GitHub) or assignee (GitLab)
        draft (bool): Create as draft PR/MR (default: false)

    Returns:
        201: PR/MR created successfully
        400: Invalid request or creation failed
        403: Access denied
        404: Project not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    source_branch = (data.get("source_branch") or "").strip()
    target_branch = (data.get("target_branch") or "main").strip()
    assignee = (data.get("assignee") or "").strip() or None
    draft = data.get("draft", False)

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not source_branch:
        return jsonify({"error": "Source branch is required"}), 400

    # Get project's issue integration to access git provider
    from ...models import ProjectIntegration

    project_integration = ProjectIntegration.query.filter_by(
        project_id=project.id
    ).first()

    if not project_integration or not project_integration.integration:
        return jsonify({
            "error": "Project has no issue integration configured"
        }), 400

    integration = project_integration.integration
    provider = integration.provider.lower()

    # Get authenticated user ID for user-specific credentials
    user_id = getattr(g, "api_user", None)
    user_id = user_id.id if user_id else None

    try:
        if provider == "github":
            result = _create_github_pr(
                integration,
                project_integration,
                title,
                description,
                source_branch,
                target_branch,
                assignee,
                draft,
                user_id,
            )
        elif provider == "gitlab":
            result = _create_gitlab_mr(
                integration,
                project_integration,
                title,
                description,
                source_branch,
                target_branch,
                assignee,
                draft,
                user_id,
            )
        else:
            return jsonify({
                "error": f"Provider '{provider}' does not support PR/MR creation"
            }), 400

        return jsonify(result), 201
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to create PR/MR: %s", exc)
        return jsonify({"error": f"Failed to create PR/MR: {str(exc)}"}), 400


def _create_github_pr(
    integration,
    project_integration,
    title: str,
    description: str,
    source_branch: str,
    target_branch: str,
    assignee: str | None,
    draft: bool,
    user_id: int | None = None,
):
    """Create a GitHub pull request."""
    import github
    from ...services.issues.utils import get_effective_integration

    # Get effective integration with user-specific credentials if user_id is provided
    effective_integration = get_effective_integration(
        integration, project_integration, user_id
    )

    token = effective_integration.api_token
    base_url = effective_integration.base_url

    # Initialize GitHub client
    if base_url:
        gh = github.Github(base_url=base_url, login_or_token=token)
    else:
        gh = github.Github(login_or_token=token)

    repo_name = project_integration.external_identifier
    repo = gh.get_repo(repo_name)

    # Create PR
    pr = repo.create_pull(
        title=title,
        body=description,
        head=source_branch,
        base=target_branch,
        draft=draft,
    )

    # Assign reviewer if specified
    if assignee:
        try:
            pr.create_review_request(reviewers=[assignee])
        except github.GithubException as exc:
            current_app.logger.warning(
                "Failed to assign reviewer %s: %s", assignee, exc
            )

    return {
        "number": pr.number,
        "title": pr.title,
        "url": pr.html_url,
        "state": pr.state,
        "draft": pr.draft,
    }


def _create_gitlab_mr(
    integration,
    project_integration,
    title: str,
    description: str,
    source_branch: str,
    target_branch: str,
    assignee: str | None,
    draft: bool,
    user_id: int | None = None,
):
    """Create a GitLab merge request."""
    import gitlab
    from ...services.issues.utils import get_effective_integration

    # Get effective integration with user-specific credentials if user_id is provided
    effective_integration = get_effective_integration(
        integration, project_integration, user_id
    )

    token = effective_integration.api_token
    base_url = effective_integration.base_url or "https://gitlab.com"

    # Initialize GitLab client
    gl = gitlab.Gitlab(base_url, private_token=token)
    gl.auth()

    project_ref = project_integration.external_identifier
    gl_project = gl.projects.get(project_ref)

    # Prepare MR data
    mr_data = {
        "source_branch": source_branch,
        "target_branch": target_branch,
        "title": ("Draft: " if draft else "") + title,
        "description": description,
    }

    # Resolve assignee username to user ID if provided
    if assignee:
        try:
            users = gl.users.list(username=assignee, get_all=False)
            if users:
                mr_data["assignee_id"] = users[0].id
        except gitlab.exceptions.GitlabError as exc:
            current_app.logger.warning(
                "Failed to resolve assignee %s: %s", assignee, exc
            )

    # Create MR
    mr = gl_project.mergerequests.create(mr_data)

    return {
        "number": mr.iid,
        "title": mr.title,
        "url": mr.web_url,
        "state": mr.state,
        "draft": draft,
    }


@api_v1_bp.post("/projects/<int:project_id>/pull-requests/<int:pr_number>/merge")
@require_api_auth(scopes=["write"])
@audit_api_request
def merge_pull_request(project_id: int, pr_number: int):
    """Merge a pull request (GitHub) or merge request (GitLab).

    Args:
        project_id: Project ID
        pr_number: PR/MR number

    Request body:
        method (str): Merge method - 'merge', 'squash', or 'rebase' (default: merge)
        delete_branch (bool): Delete source branch after merge (default: false)
        commit_message (str): Custom merge commit message (optional)

    Returns:
        200: PR/MR merged successfully
        400: Invalid request or merge failed
        403: Access denied
        404: Project or PR/MR not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}
    merge_method = (data.get("method") or "merge").strip().lower()
    delete_branch = data.get("delete_branch", False)
    commit_message = (data.get("commit_message") or "").strip() or None

    # Validate merge method
    valid_methods = {"merge", "squash", "rebase"}
    if merge_method not in valid_methods:
        return jsonify({
            "error": f"Invalid merge method '{merge_method}'. Must be one of: {', '.join(valid_methods)}"
        }), 400

    # Get project's issue integration to access git provider
    from ...models import ProjectIntegration

    project_integration = ProjectIntegration.query.filter_by(
        project_id=project.id
    ).first()

    if not project_integration or not project_integration.integration:
        return jsonify({
            "error": "Project has no issue integration configured"
        }), 400

    integration = project_integration.integration
    provider = integration.provider.lower()

    # Get authenticated user ID for user-specific credentials
    user_id = getattr(g, "api_user", None)
    user_id = user_id.id if user_id else None

    try:
        if provider == "github":
            result = _merge_github_pr(
                integration,
                project_integration,
                pr_number,
                merge_method,
                delete_branch,
                commit_message,
                user_id,
            )
        elif provider == "gitlab":
            result = _merge_gitlab_mr(
                integration,
                project_integration,
                pr_number,
                merge_method,
                delete_branch,
                commit_message,
                user_id,
            )
        else:
            return jsonify({
                "error": f"Provider '{provider}' does not support PR/MR merging"
            }), 400

        return jsonify(result), 200
    except Exception as exc:  # noqa: BLE001
        import traceback
        current_app.logger.error("Failed to merge PR/MR: %s", exc)
        current_app.logger.error("Traceback: %s", traceback.format_exc())
        return jsonify({"error": f"Failed to merge PR/MR: {str(exc)}"}), 400


def _merge_github_pr(
    integration,
    project_integration,
    pr_number: int,
    merge_method: str,
    delete_branch: bool,
    commit_message: str | None,
    user_id: int | None = None,
):
    """Merge a GitHub pull request."""
    import github
    from ...services.issues.utils import get_effective_integration

    # Get effective integration with user-specific credentials if user_id is provided
    effective_integration = get_effective_integration(
        integration, project_integration, user_id
    )

    token = effective_integration.api_token
    base_url = effective_integration.base_url

    # Initialize GitHub client
    if base_url:
        gh = github.Github(base_url=base_url, login_or_token=token)
    else:
        gh = github.Github(login_or_token=token)

    repo_name = project_integration.external_identifier
    repo = gh.get_repo(repo_name)

    # Get the PR
    pr = repo.get_pull(pr_number)

    # Merge the PR
    merge_kwargs = {
        "merge_method": merge_method,
    }
    if commit_message:
        merge_kwargs["commit_message"] = commit_message
    if delete_branch:
        # Note: delete_branch parameter in PyGithub doesn't actually delete the branch
        # We need to delete it separately after merging
        pass

    merge_result = pr.merge(**merge_kwargs)

    # Delete branch if requested (GitHub API)
    if delete_branch and merge_result.merged:
        try:
            head_ref = pr.head.ref
            repo.get_git_ref(f"heads/{head_ref}").delete()
        except Exception as e:  # noqa: BLE001
            current_app.logger.warning(f"Failed to delete branch {head_ref}: {e}")

    return {
        "merged": merge_result.merged,
        "message": merge_result.message,
        "sha": merge_result.sha,
        "pr_number": pr_number,
        "title": pr.title,
        "url": pr.html_url,
    }


def _merge_gitlab_mr(
    integration,
    project_integration,
    mr_number: int,
    merge_method: str,
    delete_branch: bool,
    commit_message: str | None,
    user_id: int | None = None,
):
    """Merge a GitLab merge request."""
    import gitlab
    from ...services.issues.utils import get_effective_integration

    # Get effective integration with user-specific credentials if user_id is provided
    effective_integration = get_effective_integration(
        integration, project_integration, user_id
    )

    token = effective_integration.api_token
    base_url = effective_integration.base_url or "https://gitlab.com"

    # Initialize GitLab client
    gl = gitlab.Gitlab(base_url, private_token=token)
    gl.auth()

    project_ref = project_integration.external_identifier
    gl_project = gl.projects.get(project_ref)

    # Get the MR
    mr = gl_project.mergerequests.get(mr_number)

    # Prepare merge options
    merge_options = {
        "should_remove_source_branch": delete_branch,
    }

    if commit_message:
        merge_options["merge_commit_message"] = commit_message

    # GitLab uses different parameter names for merge methods
    # merge_when_pipeline_succeeds can be set, but we'll merge immediately
    if merge_method == "squash":
        merge_options["squash"] = True
    # Note: GitLab doesn't have a direct rebase merge method via API
    # The "rebase" method in GitLab UI rebases then merges

    # Merge the MR
    mr.merge(**merge_options)

    # Refresh to get updated state
    mr = gl_project.mergerequests.get(mr_number)

    return {
        "merged": mr.state == "merged",
        "message": f"Merge request #{mr_number} merged successfully",
        "sha": mr.merge_commit_sha,
        "pr_number": mr_number,
        "title": mr.title,
        "url": mr.web_url,
    }


@api_v1_bp.post("/projects/<int:project_id>/pull-requests/<int:pr_number>/close")
@require_api_auth(scopes=["write"])
@audit_api_request
def close_pull_request(project_id: int, pr_number: int):
    """Close a pull request (GitHub) or merge request (GitLab).

    Args:
        project_id: Project ID
        pr_number: PR/MR number

    Returns:
        200: PR/MR closed successfully
        400: Invalid request or close failed
        403: Access denied
        404: Project or PR/MR not found
    """
    project = Project.query.get_or_404(project_id)
    if not _ensure_project_access(project):
        return jsonify({"error": "Access denied"}), 403

    # Get project's issue integration to access git provider
    from ...models import ProjectIntegration

    project_integration = ProjectIntegration.query.filter_by(
        project_id=project.id
    ).first()

    if not project_integration or not project_integration.integration:
        return jsonify({
            "error": "Project has no issue integration configured"
        }), 400

    integration = project_integration.integration
    provider = integration.provider.lower()

    # Get authenticated user ID for user-specific credentials
    user_id = getattr(g, "api_user", None)
    user_id = user_id.id if user_id else None

    try:
        if provider == "github":
            result = _close_github_pr(
                integration,
                project_integration,
                pr_number,
                user_id,
            )
        elif provider == "gitlab":
            result = _close_gitlab_mr(
                integration,
                project_integration,
                pr_number,
                user_id,
            )
        else:
            return jsonify({
                "error": f"Provider '{provider}' does not support PR/MR closing"
            }), 400

        return jsonify(result), 200
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to close PR/MR: %s", exc)
        return jsonify({"error": f"Failed to close PR/MR: {str(exc)}"}), 400


def _close_github_pr(
    integration,
    project_integration,
    pr_number: int,
    user_id: int | None = None,
):
    """Close a GitHub pull request."""
    import github
    from ...services.issues.utils import get_effective_integration

    # Get effective integration with user-specific credentials if user_id is provided
    effective_integration = get_effective_integration(
        integration, project_integration, user_id
    )

    token = effective_integration.api_token
    base_url = effective_integration.base_url

    # Initialize GitHub client
    if base_url:
        gh = github.Github(base_url=base_url, login_or_token=token)
    else:
        gh = github.Github(login_or_token=token)

    repo_name = project_integration.external_identifier
    repo = gh.get_repo(repo_name)

    # Get the PR
    pr = repo.get_pull(pr_number)

    # Close the PR by editing its state
    pr.edit(state="closed")

    return {
        "closed": True,
        "message": f"Pull request #{pr_number} closed successfully",
        "pr_number": pr_number,
        "title": pr.title,
        "url": pr.html_url,
        "state": "closed",
    }


def _close_gitlab_mr(
    integration,
    project_integration,
    mr_number: int,
    user_id: int | None = None,
):
    """Close a GitLab merge request."""
    import gitlab
    from ...services.issues.utils import get_effective_integration

    # Get effective integration with user-specific credentials if user_id is provided
    effective_integration = get_effective_integration(
        integration, project_integration, user_id
    )

    token = effective_integration.api_token
    base_url = effective_integration.base_url or "https://gitlab.com"

    # Initialize GitLab client
    gl = gitlab.Gitlab(base_url, private_token=token)
    gl.auth()

    project_ref = project_integration.external_identifier
    gl_project = gl.projects.get(project_ref)

    # Get the MR
    mr = gl_project.mergerequests.get(mr_number)

    # Close the MR by updating its state
    mr.state_event = "close"
    mr.save()

    # Refresh to get updated state
    mr = gl_project.mergerequests.get(mr_number)

    return {
        "closed": mr.state == "closed",
        "message": f"Merge request #{mr_number} closed successfully",
        "pr_number": mr_number,
        "title": mr.title,
        "url": mr.web_url,
        "state": mr.state,
    }
