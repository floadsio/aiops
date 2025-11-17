"""API v1 AI agent workflow endpoints.

These endpoints provide high-level workflows for AI agents to autonomously
manage issues, code changes, and development tasks.
"""

from __future__ import annotations

from datetime import datetime

from flask import current_app, g, jsonify, request
from sqlalchemy.orm import selectinload

from ...extensions import db
from ...models import ExternalIssue, Project, ProjectIntegration
from ...services.api_auth import audit_api_request, require_api_auth
from ...services.workspace_service import get_workspace_status
from . import api_v1_bp


@api_v1_bp.post("/workflows/claim-issue")
@require_api_auth(scopes=["write"])
@audit_api_request
def claim_issue():
    """Claim an issue for work by assigning it to the current user.

    This is a high-level workflow that:
    1. Assigns the issue to the current user (via User Identity mapping)
    2. Updates issue status to "in progress" (if supported by provider)
    3. Returns issue details and workspace information

    Request body:
        issue_id (int): Issue ID to claim (required)

    Returns:
        200: Issue claimed successfully with workspace info
        400: Invalid request
        404: Issue not found
    """
    user = g.api_user
    data = request.get_json(silent=True) or {}
    issue_id = data.get("issue_id")

    if not issue_id:
        return jsonify({"error": "issue_id is required"}), 400

    # Get the issue with related data
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration)
        .selectinload(ProjectIntegration.project),
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get(issue_id)

    if not issue:
        return jsonify({"error": "Issue not found"}), 404

    project = issue.project_integration.project
    integration = issue.project_integration.integration

    # Get user identity for the provider
    from ...services.user_identity_service import get_user_identity

    identity_map = get_user_identity(user.id)

    provider = integration.provider.lower()

    # Check for per-project username override first
    assignee = None
    if issue.project_integration.override_settings:
        assignee = issue.project_integration.override_settings.get("username")

    # Fall back to global user identity mapping
    if not assignee and identity_map:
        if provider == "github":
            assignee = identity_map.github_username
        elif provider == "gitlab":
            assignee = identity_map.gitlab_username
        elif provider == "jira":
            assignee = identity_map.jira_account_id

    if not assignee:
        return jsonify({"error": f"No {provider} identity configured for user"}), 400

    # Assign issue via provider (best effort - don't fail if not supported)
    from .issues import _get_issue_provider

    assignment_error = None
    try:
        provider_obj = _get_issue_provider(integration)
        provider_obj.assign_issue(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            assignee=assignee,
        )
        # Update local database only if provider assignment succeeded
        issue.assignee = assignee
        issue.last_seen_at = datetime.utcnow()
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        # Log the error but don't fail the request
        current_app.logger.warning(
            "Failed to assign issue %s via %s provider: %s",
            issue.external_id,
            provider,
            exc,
        )
        assignment_error = str(exc)

    # Get workspace status
    workspace_status = get_workspace_status(project, user)

    from .issues import _issue_to_dict

    response = {
        "message": "Issue claimed successfully",
        "issue": _issue_to_dict(issue),
        "workspace": workspace_status,
        "next_steps": [
            f"Workspace path: {workspace_status.get('path', 'N/A')}",
            "Initialize workspace if not already done: POST /api/v1/projects/{id}/workspace/init",
            "Create a branch for this issue: POST /api/v1/projects/{id}/git/branches",
            "Make your changes and commit: POST /api/v1/projects/{id}/git/commit",
        ],
    }

    # Include warning if assignment failed
    if assignment_error:
        response["warning"] = f"Could not assign issue on {provider}: {assignment_error}"

    return jsonify(response)


@api_v1_bp.post("/workflows/update-progress")
@require_api_auth(scopes=["write"])
@audit_api_request
def update_progress():
    """Update issue progress with a status comment.

    Request body:
        issue_id (int): Issue ID (required)
        status (str): Status update (e.g., "in progress", "blocked", "review")
        comment (str, optional): Additional comment to add

    Returns:
        200: Progress updated successfully
        400: Invalid request
        404: Issue not found
    """
    data = request.get_json(silent=True) or {}
    issue_id = data.get("issue_id")
    status = (data.get("status") or "").strip()
    comment = (data.get("comment") or "").strip()

    if not issue_id or not status:
        return jsonify({"error": "issue_id and status are required"}), 400

    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get(issue_id)

    if not issue:
        return jsonify({"error": "Issue not found"}), 404

    integration = issue.project_integration.integration

    # Build comment text
    comment_text = f"**Status Update:** {status}"
    if comment:
        comment_text += f"\n\n{comment}"

    # Add comment via provider
    from .issues import _get_issue_provider

    try:
        provider = _get_issue_provider(integration)
        comment_data = provider.add_comment(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            body=comment_text,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Failed to update progress: {str(exc)}"}), 500

    # Update local comments cache
    comments = issue.comments or []
    comments.append(comment_data)
    issue.comments = comments
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message": "Progress updated successfully",
        "status": status,
        "comment": comment_data,
    })


@api_v1_bp.post("/workflows/submit-changes")
@require_api_auth(scopes=["write"])
@audit_api_request
def submit_changes():
    """Submit changes for an issue by creating a commit and commenting on the issue.

    Request body:
        issue_id (int): Issue ID (required)
        project_id (int): Project ID (required)
        commit_message (str): Commit message (required)
        files (list[str], optional): Specific files to commit
        comment (str, optional): Additional comment to add to issue

    Returns:
        200: Changes submitted successfully
        400: Invalid request
        404: Issue or project not found
    """
    user = g.api_user
    data = request.get_json(silent=True) or {}
    issue_id = data.get("issue_id")
    project_id = data.get("project_id")
    commit_message = (data.get("commit_message") or "").strip()
    files = data.get("files", [])
    comment = (data.get("comment") or "").strip()

    if not issue_id or not project_id or not commit_message:
        return jsonify({
            "error": "issue_id, project_id, and commit_message are required"
        }), 400

    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get(issue_id)

    if not issue:
        return jsonify({"error": "Issue not found"}), 404

    project = Project.query.get(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Create commit
    from ...services.workspace_service import get_workspace_path
    from ...services.sudo_service import run_as_user
    from ...services.linux_users import resolve_linux_username

    linux_username = resolve_linux_username(user)
    workspace_path = get_workspace_path(project, user)

    try:
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
        commit_result = run_as_user(
            linux_username,
            ["git", "-C", str(workspace_path), "commit", "-m", commit_message],
            timeout=30.0,
        )

        # Get commit hash
        hash_result = run_as_user(
            linux_username,
            ["git", "-C", str(workspace_path), "rev-parse", "HEAD"],
            timeout=5.0,
        )
        commit_hash = hash_result.stdout.strip()[:7]  # Short hash

    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Failed to create commit: {str(exc)}"}), 400

    # Add comment to issue with commit info
    integration = issue.project_integration.integration
    comment_text = f"**Changes Committed**\n\nCommit: `{commit_hash}`\nMessage: {commit_message}"
    if comment:
        comment_text += f"\n\n{comment}"

    from .issues import _get_issue_provider

    try:
        provider = _get_issue_provider(integration)
        comment_data = provider.add_comment(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            body=comment_text,
        )
    except Exception:  # noqa: BLE001
        # Don't fail if comment fails, commit is more important
        comment_data = None

    # Update local comments cache
    if comment_data:
        comments = issue.comments or []
        comments.append(comment_data)
        issue.comments = comments
        issue.last_seen_at = datetime.utcnow()
        db.session.commit()

    return jsonify({
        "message": "Changes submitted successfully",
        "commit_hash": commit_hash,
        "commit_output": commit_result.stdout,
        "comment": comment_data,
    })


@api_v1_bp.post("/workflows/request-approval")
@require_api_auth(scopes=["write"])
@audit_api_request
def request_approval():
    """Request approval for changes by adding a review request comment.

    Request body:
        issue_id (int): Issue ID (required)
        message (str, optional): Custom approval request message

    Returns:
        200: Approval requested successfully
        400: Invalid request
        404: Issue not found
    """
    data = request.get_json(silent=True) or {}
    issue_id = data.get("issue_id")
    message = (data.get("message") or "").strip()

    if not issue_id:
        return jsonify({"error": "issue_id is required"}), 400

    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get(issue_id)

    if not issue:
        return jsonify({"error": "Issue not found"}), 404

    integration = issue.project_integration.integration

    # Build approval request comment
    comment_text = "**\U0001F4DD Review Request**\n\nChanges are ready for review."
    if message:
        comment_text += f"\n\n{message}"

    # Add comment via provider
    from .issues import _get_issue_provider

    try:
        provider = _get_issue_provider(integration)
        comment_data = provider.add_comment(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            body=comment_text,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Failed to request approval: {str(exc)}"}), 500

    # Update local comments cache
    comments = issue.comments or []
    comments.append(comment_data)
    issue.comments = comments
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message": "Approval requested successfully",
        "comment": comment_data,
    })


@api_v1_bp.post("/workflows/complete-issue")
@require_api_auth(scopes=["write"])
@audit_api_request
def complete_issue():
    """Mark an issue as completed.

    This workflow:
    1. Adds a completion comment
    2. Closes the issue
    3. Returns final issue status

    Request body:
        issue_id (int): Issue ID (required)
        summary (str, optional): Completion summary

    Returns:
        200: Issue completed successfully
        400: Invalid request
        404: Issue not found
    """
    data = request.get_json(silent=True) or {}
    issue_id = data.get("issue_id")
    summary = (data.get("summary") or "").strip()

    if not issue_id:
        return jsonify({"error": "issue_id is required"}), 400

    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get(issue_id)

    if not issue:
        return jsonify({"error": "Issue not found"}), 404

    integration = issue.project_integration.integration

    # Add completion comment
    comment_text = "**\u2705 Issue Completed**"
    if summary:
        comment_text += f"\n\n{summary}"

    from .issues import _get_issue_provider

    try:
        provider = _get_issue_provider(integration)

        # Add comment
        comment_data = provider.add_comment(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            body=comment_text,
        )

        # Close issue
        provider.close_issue(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Failed to complete issue: {str(exc)}"}), 500

    # Update local database
    comments = issue.comments or []
    comments.append(comment_data)
    issue.comments = comments
    issue.status = "closed"
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    from .issues import _issue_to_dict

    return jsonify({
        "message": "Issue completed successfully",
        "issue": _issue_to_dict(issue),
    })
