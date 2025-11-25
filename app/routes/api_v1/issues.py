"""API v1 issue management endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import current_app, g, jsonify, request
from sqlalchemy.orm import selectinload

from ...extensions import db
from ...models import ExternalIssue, Project, ProjectIntegration, TenantIntegration
from ...services.api_auth import audit_api_request, require_api_auth
from ...services.issues.providers import (
    GitHubIssueProvider,
    GitLabIssueProvider,
    JiraIssueProvider,
)
from ...services.issues import (
    IssueSyncError,
    serialize_issue_comments,
    sync_tenant_integrations,
)
from ...services.issues.utils import normalize_issue_status
from ...services.user_identity_service import get_user_identity  # type: ignore
from . import api_v1_bp


def _serialize_timestamp(value: datetime | None) -> str | None:
    """Convert datetime to ISO format string."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _issue_to_dict(issue: ExternalIssue) -> dict[str, Any]:
    """Convert ExternalIssue model to dictionary.

    Args:
        issue: The external issue model

    Returns:
        dict: Issue data
    """
    integration = (
        issue.project_integration.integration if issue.project_integration else None
    )
    project = (
        issue.project_integration.project if issue.project_integration else None
    )
    tenant = project.tenant if project else None
    status_key, status_label = normalize_issue_status(issue.status)
    updated_reference = (
        issue.external_updated_at or issue.updated_at or issue.created_at
    )
    provider_key = (
        (integration.provider or "").lower()
        if integration and integration.provider
        else ""
    )

    return {
        "id": issue.id,
        "external_id": issue.external_id,
        "title": issue.title,
        "status": issue.status,
        "status_key": status_key,
        "status_label": status_label,
        "assignee": issue.assignee,
        "url": issue.url,
        "labels": issue.labels or [],
        "comments": issue.comments or [],
        "provider": integration.provider if integration else None,
        "provider_key": provider_key,
        "integration_name": integration.name if integration else None,
        "integration_id": integration.id if integration else None,
        "project_id": project.id if project else None,
        "project_name": project.name if project else None,
        "tenant_id": tenant.id if tenant else None,
        "tenant_name": tenant.name if tenant else None,
        "updated_at": _serialize_timestamp(updated_reference),
        "created_at": _serialize_timestamp(issue.created_at),
    }


def _get_issue_provider(integration: TenantIntegration):
    """Get the appropriate issue provider for an integration.

    Args:
        integration: The tenant integration

    Returns:
        Issue provider instance

    Raises:
        ValueError: If provider is not supported
    """
    provider = integration.provider.lower()
    if provider == "github":
        return GitHubIssueProvider(integration)
    elif provider == "gitlab":
        return GitLabIssueProvider(integration)
    elif provider == "jira":
        return JiraIssueProvider(integration)
    else:
        raise ValueError(f"Unsupported provider: {integration.provider}")


@api_v1_bp.get("/issues")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_issues():
    """List all issues with filtering options.

    Query params:
        status (str, optional): Filter by status (open, closed, all)
        provider (str, optional): Filter by provider (github, gitlab, jira)
        project_id (int, optional): Filter by project
        tenant_id (int, optional): Filter by tenant
        assignee (str, optional): Filter by assignee
        labels (str, optional): Comma-separated list of labels
        limit (int, optional): Limit number of results
        offset (int, optional): Offset for pagination

    Returns:
        200: List of issues
    """
    # Parse query parameters
    status_filter = (request.args.get("status") or "").strip().lower()
    if status_filter == "all":
        status_filter = ""

    provider_filter = (request.args.get("provider") or "").strip().lower()
    if provider_filter == "all":
        provider_filter = ""

    project_id = request.args.get("project_id", type=int)
    tenant_id = request.args.get("tenant_id", type=int)
    assignee = request.args.get("assignee")
    labels_str = request.args.get("labels")
    labels_filter = [label.strip() for label in labels_str.split(",")] if labels_str else []
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int, default=0)

    # Build query
    query = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration)
        .selectinload(ProjectIntegration.project)
        .selectinload(Project.tenant),
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    )

    if project_id is not None:
        query = query.join(ProjectIntegration).filter(
            ProjectIntegration.project_id == project_id
        )

    if tenant_id is not None:
        query = (
            query.join(ProjectIntegration)
            .join(Project)
            .filter(Project.tenant_id == tenant_id)
        )

    # Fetch and filter issues
    issues = query.all()
    payload: list[dict[str, Any]] = []

    for issue in issues:
        issue_payload = _issue_to_dict(issue)

        # Apply filters
        if status_filter and issue_payload["status_key"] != status_filter:
            continue
        if provider_filter and issue_payload.get("provider_key") != provider_filter:
            continue
        if assignee:
            issue_assignee = issue_payload.get("assignee") or ""
            if assignee.lower() not in issue_assignee.lower():
                continue
        if labels_filter:
            issue_labels = set(issue_payload.get("labels", []))
            if not any(label in issue_labels for label in labels_filter):
                continue

        payload.append(issue_payload)

    # Apply pagination
    total = len(payload)
    if offset:
        payload = payload[offset:]
    if isinstance(limit, int) and limit > 0:
        payload = payload[:limit]

    return jsonify({
        "issues": payload,
        "count": len(payload),
        "total": total,
        "offset": offset,
        "limit": limit,
    })


@api_v1_bp.get("/issues/pinned")
@require_api_auth(scopes=["read"])
@audit_api_request
def list_pinned_issues():
    """List pinned issues for the current user.

    Returns:
        200: List of pinned issues with metadata
    """
    from ...models import PinnedIssue

    user = g.api_user

    # Query pinned issues for the current user
    pinned_issues = (
        PinnedIssue.query.filter_by(user_id=user.id)
        .join(ExternalIssue)
        .join(ProjectIntegration)
        .options(
            selectinload(PinnedIssue.issue)
            .selectinload(ExternalIssue.project_integration)
            .selectinload(ProjectIntegration.project)
            .selectinload(Project.tenant),
            selectinload(PinnedIssue.issue)
            .selectinload(ExternalIssue.project_integration)
            .selectinload(ProjectIntegration.integration),
        )
        .order_by(PinnedIssue.pinned_at.desc())
        .all()
    )

    payload = []
    for pinned in pinned_issues:
        issue_dict = _issue_to_dict(pinned.issue)
        issue_dict["pinned_at"] = _serialize_timestamp(pinned.pinned_at)
        payload.append(issue_dict)

    return jsonify({
        "issues": payload,
        "count": len(payload),
    })


@api_v1_bp.post("/issues/<int:issue_id>/pin")
@require_api_auth(scopes=["write"])
@audit_api_request
def pin_issue(issue_id: int):
    """Pin an issue for quick access.

    Args:
        issue_id: Issue ID to pin

    Returns:
        200: Issue pinned successfully
        404: Issue not found
    """
    from ...models import PinnedIssue

    user = g.api_user

    # Verify issue exists (raises 404 if not found)
    ExternalIssue.query.get_or_404(issue_id)

    # Check if already pinned
    existing = PinnedIssue.query.filter_by(
        user_id=user.id, issue_id=issue_id
    ).first()

    if existing:
        return jsonify({"message": "Issue is already pinned"}), 200

    # Create pin
    pinned = PinnedIssue(user_id=user.id, issue_id=issue_id)
    db.session.add(pinned)
    db.session.commit()

    return jsonify({
        "message": "Issue pinned successfully",
        "issue_id": issue_id,
        "pinned_at": _serialize_timestamp(pinned.pinned_at),
    })


@api_v1_bp.delete("/issues/<int:issue_id>/pin")
@require_api_auth(scopes=["write"])
@audit_api_request
def unpin_issue(issue_id: int):
    """Unpin an issue.

    Args:
        issue_id: Issue ID to unpin

    Returns:
        200: Issue unpinned successfully
        404: Issue not found or not pinned
    """
    from ...models import PinnedIssue

    user = g.api_user

    # Find pinned issue
    pinned = PinnedIssue.query.filter_by(
        user_id=user.id, issue_id=issue_id
    ).first()

    if not pinned:
        return jsonify({"error": "Issue is not pinned"}), 404

    # Remove pin
    db.session.delete(pinned)
    db.session.commit()

    return jsonify({
        "message": "Issue unpinned successfully",
        "issue_id": issue_id,
    })


@api_v1_bp.get("/issues/<int:issue_id>")
@require_api_auth(scopes=["read"])
@audit_api_request
def get_issue(issue_id: int):
    """Get a specific issue by ID.

    Args:
        issue_id: Issue ID

    Returns:
        200: Issue data with full details
        404: Issue not found
    """
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration)
        .selectinload(ProjectIntegration.project)
        .selectinload(Project.tenant),
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get_or_404(issue_id)

    return jsonify({"issue": _issue_to_dict(issue)})


@api_v1_bp.post("/issues")
@require_api_auth(scopes=["write"])
@audit_api_request
def create_issue():
    """Create a new issue on the external provider.

    Request body:
        project_id (int): Project ID (required)
        integration_id (int): Integration ID (required)
        title (str): Issue title (required)
        description (str, optional): Issue description/body
        labels (list[str], optional): Issue labels
        assignee (str, optional): Assignee username (will use User Identity mapping)

    Returns:
        201: Created issue
        400: Invalid request
        404: Project or integration not found
    """
    user = g.api_user
    data = request.get_json(silent=True) or {}

    project_id = data.get("project_id")
    integration_id = data.get("integration_id")
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip() or None
    labels = data.get("labels", [])
    assignee_username = data.get("assignee")

    # Validate required fields
    if not title:
        return jsonify({"error": "Issue title is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not integration_id:
        return jsonify({"error": "integration_id is required"}), 400

    # Get project and integration
    project = Project.query.get(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    integration = TenantIntegration.query.get(integration_id)
    if not integration:
        return jsonify({"error": "Integration not found"}), 404

    # Verify integration belongs to project's tenant
    if integration.tenant_id != project.tenant_id:
        return jsonify({"error": "Integration does not belong to project's tenant"}), 400

    # Get project integration
    project_integration = ProjectIntegration.query.filter_by(
        project_id=project_id, integration_id=integration_id
    ).first()
    if not project_integration:
        return jsonify({"error": "Project is not linked to this integration"}), 404

    # Map assignee to provider-specific identity
    # If no assignee specified, default to the user creating the issue
    assignee_identity = None
    identity_map = get_user_identity(user.id)
    if identity_map:
        provider_type = integration.provider.lower()
        if assignee_username:
            # Explicit assignee provided - use that
            if provider_type == "github":
                assignee_identity = identity_map.github_username
            elif provider_type == "gitlab":
                assignee_identity = identity_map.gitlab_username
            elif provider_type == "jira":
                assignee_identity = identity_map.jira_account_id
        else:
            # No assignee specified - assign to creator
            if provider_type == "github":
                assignee_identity = identity_map.github_username
            elif provider_type == "gitlab":
                assignee_identity = identity_map.gitlab_username
            elif provider_type == "jira":
                assignee_identity = identity_map.jira_account_id

    # Create issue via provider (with user-specific credentials if available)
    try:
        provider = _get_issue_provider(integration)
        external_issue_data = provider.create_issue(
            project_integration=project_integration,
            title=title,
            description=description or "",
            labels=labels,
            assignee=assignee_identity,
            user_id=user.id,
        )
    except IssueSyncError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to create issue: %s", exc)
        return jsonify({"error": f"Failed to create issue: {str(exc)}"}), 500

    # Store in database
    issue = ExternalIssue(
        project_integration_id=project_integration.id,
        external_id=external_issue_data.get("external_id", ""),
        title=external_issue_data.get("title", title),
        status=external_issue_data.get("status"),
        assignee=external_issue_data.get("assignee"),
        url=external_issue_data.get("url"),
        labels=external_issue_data.get("labels", labels),
        raw_payload=external_issue_data,
        last_seen_at=datetime.utcnow(),
    )
    db.session.add(issue)
    db.session.commit()

    return jsonify({"issue": _issue_to_dict(issue)}), 201


@api_v1_bp.patch("/issues/<int:issue_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def update_issue(issue_id: int):
    """Update an existing issue.

    Args:
        issue_id: Issue ID

    Request body:
        title (str, optional): New issue title
        description (str, optional): New issue description
        status (str, optional): New issue status
        labels (list[str], optional): New issue labels

    Returns:
        200: Updated issue
        404: Issue not found
    """
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get_or_404(issue_id)

    data = request.get_json(silent=True) or {}
    integration = issue.project_integration.integration

    try:
        provider = _get_issue_provider(integration)
        updated_data = provider.update_issue(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            title=data.get("title"),
            description=data.get("description"),
            status=data.get("status"),
            labels=data.get("labels"),
        )
    except IssueSyncError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to update issue: %s", exc)
        return jsonify({"error": f"Failed to update issue: {str(exc)}"}), 500

    # Update local database
    if updated_data.get("title"):
        issue.title = updated_data["title"]
    if updated_data.get("status"):
        issue.status = updated_data["status"]
    if updated_data.get("labels") is not None:
        issue.labels = updated_data["labels"]
    if updated_data.get("assignee") is not None:
        issue.assignee = updated_data["assignee"]

    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"issue": _issue_to_dict(issue)})


@api_v1_bp.post("/issues/<int:issue_id>/close")
@require_api_auth(scopes=["write"])
@audit_api_request
def close_issue(issue_id: int):
    """Close an issue.

    Args:
        issue_id: Issue ID

    Returns:
        200: Closed issue
        404: Issue not found
    """
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get_or_404(issue_id)

    integration = issue.project_integration.integration

    try:
        provider = _get_issue_provider(integration)
        provider.close_issue(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
        )
    except IssueSyncError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to close issue: %s", exc)
        return jsonify({"error": f"Failed to close issue: {str(exc)}"}), 500

    # Update local status
    issue.status = "closed"
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"issue": _issue_to_dict(issue)})


@api_v1_bp.post("/issues/<int:issue_id>/reopen")
@require_api_auth(scopes=["write"])
@audit_api_request
def reopen_issue(issue_id: int):
    """Reopen a closed issue.

    Args:
        issue_id: Issue ID

    Returns:
        200: Reopened issue
        404: Issue not found
    """
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get_or_404(issue_id)

    integration = issue.project_integration.integration

    try:
        provider = _get_issue_provider(integration)
        provider.reopen_issue(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
        )
    except IssueSyncError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to reopen issue: %s", exc)
        return jsonify({"error": f"Failed to reopen issue: {str(exc)}"}), 500

    # Update local status
    issue.status = "open"
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"issue": _issue_to_dict(issue)})


@api_v1_bp.post("/issues/<int:issue_id>/comments")
@require_api_auth(scopes=["write"])
@audit_api_request
def add_issue_comment(issue_id: int):
    """Add a comment to an issue.

    Args:
        issue_id: Issue ID

    Request body:
        body (str): Comment text (required)

    Returns:
        201: Comment added successfully
        400: Invalid request
        404: Issue not found
    """
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get_or_404(issue_id)

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()

    if not body:
        return jsonify({"error": "Comment body is required"}), 400

    integration = issue.project_integration.integration

    # Get authenticated user ID for user-specific credentials
    user_id = getattr(g, "api_user", None)
    user_id = user_id.id if user_id else None

    try:
        provider = _get_issue_provider(integration)
        comment_data = provider.add_comment(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            body=body,
            user_id=user_id,
        )
    except IssueSyncError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to add comment: %s", exc)
        return jsonify({"error": f"Failed to add comment: {str(exc)}"}), 500

    # Update local comments cache
    comments = issue.comments or []
    comments.append(comment_data)
    issue.comments = comments
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message": "Comment added successfully",
        "comment": comment_data,
    }), 201


@api_v1_bp.patch("/issues/<int:issue_id>/comments/<comment_id>")
@require_api_auth(scopes=["write"])
@audit_api_request
def update_issue_comment(issue_id: int, comment_id: str):
    """Update an existing comment on an issue.

    Args:
        issue_id: Issue ID
        comment_id: Comment ID to update

    Request body:
        body (str): New comment text (required)

    Returns:
        200: Comment updated successfully
        400: Invalid request
        404: Issue not found
    """
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get_or_404(issue_id)

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()

    if not body:
        return jsonify({"error": "Comment body is required"}), 400

    integration = issue.project_integration.integration

    try:
        provider = _get_issue_provider(integration)
        # Check if provider supports update_comment
        if not hasattr(provider, "update_comment"):
            return jsonify({"error": f"{integration.provider} does not support updating comments"}), 400

        comment_data = provider.update_comment(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            comment_id=comment_id,
            body=body,
            user_id=g.api_user.id if hasattr(g, "api_user") else None,
        )
    except IssueSyncError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to update comment: %s", exc)
        return jsonify({"error": f"Failed to update comment: {str(exc)}"}), 500

    # Update local comments cache
    # Find and update the comment in the cached list
    comments = issue.comments or []
    for i, comment in enumerate(comments):
        # Match by comment body or other identifier if available
        # Note: This is a best-effort update since we don't store comment IDs locally
        if isinstance(comment, dict):
            # We'll update the most recent comment with matching author
            # This is imperfect but workable for now
            if comment.get("author") == comment_data.get("author"):
                comments[i] = comment_data
                break
    else:
        # If not found, just append (shouldn't happen normally)
        comments.append(comment_data)

    issue.comments = comments
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message": "Comment updated successfully",
        "comment": comment_data,
    }), 200


@api_v1_bp.post("/issues/<int:issue_id>/assign")
@require_api_auth(scopes=["write"])
@audit_api_request
def assign_issue(issue_id: int):
    """Assign an issue to a user.

    Uses User Identity mapping to convert aiops user to provider-specific identity.

    Args:
        issue_id: Issue ID

    Request body:
        user_id (int, optional): AIops user ID to assign
        assignee (str, optional): Provider-specific username to assign

    Returns:
        200: Issue assigned successfully
        400: Invalid request
        404: Issue or user not found
    """
    issue = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).get_or_404(issue_id)

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    assignee = data.get("assignee")

    integration = issue.project_integration.integration

    # Map user_id to provider-specific identity if provided
    if user_id:
        identity_map = get_user_identity(user_id)
        if not identity_map:
            return jsonify({"error": "User identity mapping not found"}), 404

        provider = integration.provider.lower()
        if provider == "github":
            assignee = identity_map.github_username
        elif provider == "gitlab":
            assignee = identity_map.gitlab_username
        elif provider == "jira":
            assignee = identity_map.jira_account_id

    if not assignee:
        return jsonify({"error": "Either user_id or assignee must be provided"}), 400

    try:
        provider = _get_issue_provider(integration)
        provider.assign_issue(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            assignee=assignee,
        )
    except IssueSyncError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to assign issue: %s", exc)
        return jsonify({"error": f"Failed to assign issue: {str(exc)}"}), 500

    # Update local assignee
    issue.assignee = assignee
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"issue": _issue_to_dict(issue)})


@api_v1_bp.post("/issues/sync")
@require_api_auth(scopes=["write"])
@audit_api_request
def sync_issues():
    """Synchronize issues from external providers.

    Request body:
        tenant_id (int, optional): Limit sync to a specific tenant
        integration_id (int, optional): Limit sync to a specific tenant integration
        project_id (int, optional): Limit sync to a specific project
        force_full (bool, optional): Force full sync (default: False)

    Returns:
        200: Sync completed successfully with statistics
        400: Invalid request
        404: Tenant or integration not found
        500: Sync failed
    """
    data = request.get_json(silent=True) or {}

    tenant_id = data.get("tenant_id")
    integration_id = data.get("integration_id")
    project_id = data.get("project_id")
    force_full = data.get("force_full", False)

    # Validate tenant and integration relationship if both provided
    if tenant_id is not None and integration_id is not None:
        integration = TenantIntegration.query.get(integration_id)
        if integration is None or integration.tenant_id != tenant_id:
            return jsonify({"error": "Integration does not belong to the provided tenant"}), 400

    # Build query for project integrations
    query = (
        ProjectIntegration.query.options(
            selectinload(ProjectIntegration.project),
            selectinload(ProjectIntegration.integration).selectinload(
                TenantIntegration.tenant
            ),
        )
        .join(ProjectIntegration.integration)
        .filter(TenantIntegration.enabled.is_(True))
    )

    # Apply filters
    if tenant_id is not None:
        query = query.filter(TenantIntegration.tenant_id == tenant_id)
    if integration_id is not None:
        query = query.filter(ProjectIntegration.integration_id == integration_id)
    if project_id is not None:
        query = query.filter(ProjectIntegration.project_id == project_id)

    project_integrations = query.all()
    if not project_integrations:
        return jsonify({
            "message": "No project integrations matched the filters",
            "synced": 0,
            "projects": [],
        })

    # Perform sync - now gracefully handles failures
    results = sync_tenant_integrations(project_integrations, force_full=force_full)

    # Build response with statistics - separate successful from failed integrations
    projects_synced = []
    projects_failed = []
    total_issues = 0

    for project_integration in project_integrations:
        tenant_name = (
            project_integration.integration.tenant.name
            if project_integration.integration.tenant
            else "Unknown tenant"
        )
        project_name = (
            project_integration.project.name
            if project_integration.project
            else "Unknown project"
        )
        integration_name = (
            project_integration.integration.name
            if project_integration.integration
            else "Unknown integration"
        )
        provider = project_integration.integration.provider

        # Check if this integration was successfully synced
        if project_integration.id in results:
            count = len(results[project_integration.id])
            total_issues += count
            projects_synced.append({
                "project_integration_id": project_integration.id,
                "project_id": project_integration.project_id,
                "project_name": project_name,
                "tenant_name": tenant_name,
                "integration_name": integration_name,
                "provider": provider,
                "issues_synced": count,
                "status": "success",
            })
        else:
            # Integration failed to sync
            projects_failed.append({
                "project_integration_id": project_integration.id,
                "project_id": project_integration.project_id,
                "project_name": project_name,
                "tenant_name": tenant_name,
                "integration_name": integration_name,
                "provider": provider,
                "status": "failed",
            })

    # Build summary message
    success_count = len(projects_synced)
    failure_count = len(projects_failed)

    if failure_count > 0:
        if success_count > 0:
            message = (
                f"Issue synchronization partially completed: "
                f"{success_count} integrations succeeded, {failure_count} failed"
            )
        else:
            message = f"Issue synchronization failed for all {failure_count} integrations"
    else:
        message = "Issue synchronization completed successfully"

    return jsonify({
        "message": message,
        "synced": total_issues,
        "success_count": success_count,
        "failure_count": failure_count,
        "projects": projects_synced,
        "failed_projects": projects_failed,
    })


@api_v1_bp.route("/issues/create-assisted", methods=["POST"])
@require_api_auth(scopes=["write"])
def create_assisted_issue():
    """Create an issue using AI to generate content from a natural language description.

    This endpoint uses an AI tool to generate a well-formatted issue from a user's
    natural language description. It can optionally create a feature branch and
    start an AI session for working on the issue.

    Request body:
        project_id (int): ID of the project
        integration_id (int): ID of the project integration (GitHub/GitLab/Jira)
        description (str): Natural language description of what to work on
        ai_tool (str): AI tool to use for generation (claude, codex, gemini)
        issue_type (str, optional): Hint about issue type (feature, bug)
        create_branch (bool, optional): Whether to create a feature branch (default: false)
        start_session (bool, optional): Whether to start an AI session (default: false)
        assignee_user_id (int, optional): User ID to assign the issue to

    Returns:
        JSON response with:
            - issue_id: Created issue database ID
            - issue_url: External issue URL
            - external_id: External issue number/key
            - title: Generated issue title
            - branch_name: Created branch name (if create_branch=true)
            - session_id: Created session ID (if start_session=true)
            - session_url: URL to attach to session (if start_session=true)
    """
    from ...services.ai_issue_generator import (
        AIIssueGenerationError,
        generate_branch_name,
        generate_issue_from_description,
    )
    from ...services.git_service import checkout_or_create_branch
    from ...services.issues import create_issue_for_project_integration

    audit_api_request("POST", "/api/v1/issues/create-assisted")

    data = request.get_json() or {}

    # Validate required fields
    project_id = data.get("project_id")
    integration_id = data.get("integration_id")
    description = data.get("description", "").strip()
    ai_tool = data.get("ai_tool", current_app.config.get("DEFAULT_AI_TOOL", "claude"))

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not integration_id:
        return jsonify({"error": "integration_id is required"}), 400
    if not description:
        return jsonify({"error": "description is required"}), 400

    # Optional fields
    issue_type = data.get("issue_type")
    create_branch = data.get("create_branch", False)
    start_session = data.get("start_session", False)
    assignee_user_id = data.get("assignee_user_id")

    # Validate project exists
    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": f"Project {project_id} not found"}), 404

    # Validate integration exists and belongs to project
    integration = db.session.get(ProjectIntegration, integration_id)
    if not integration or integration.project_id != project_id:
        return jsonify({"error": f"Integration {integration_id} not found for project"}), 404

    try:
        # Step 1: Generate issue content using AI
        try:
            issue_data = generate_issue_from_description(description, ai_tool, issue_type)
        except AIIssueGenerationError as e:
            return jsonify({
                "error": "AI generation failed",
                "details": str(e),
            }), 500

        # Step 2: Create the issue and persist it locally
        try:
            # Pass creator_user_id to ensure issue is created with correct user's credentials
            creator_user_id = g.current_user.id if hasattr(g, "current_user") else None
            issue_payload = create_issue_for_project_integration(
                project_integration=integration,
                summary=issue_data["title"],
                description=issue_data["description"],
                labels=issue_data.get("labels", []),
                issue_type=issue_type,
                assignee_user_id=assignee_user_id,
                creator_user_id=creator_user_id,
            )

            from ...models import ExternalIssue

            issue = ExternalIssue(
                project_integration_id=integration.id,
                external_id=issue_payload.external_id,
                title=issue_payload.title,
                status=issue_payload.status,
                assignee=issue_payload.assignee,
                url=issue_payload.url,
                labels=issue_payload.labels or [],
                external_updated_at=issue_payload.external_updated_at,
                last_seen_at=datetime.now(timezone.utc),
                raw_payload=issue_payload.raw,
                comments=serialize_issue_comments(issue_payload.comments or []),
            )
            db.session.add(issue)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({
                "error": "Failed to create issue",
                "details": str(e),
            }), 500

        response_data = {
            "issue_id": issue.id,
            "issue_url": issue.url,
            "external_id": issue.external_id,
            "title": issue.title,
            "description": issue_data.get("description"),
            "labels": issue.labels,
            "status": issue.status,
            "cli_commands": {
                "work_on_issue": f"aiops issues work {issue.id}",
                "get_details": f"aiops issues get {issue.id} --output json",
                "add_comment": f"aiops issues comment {issue.id} \"Your update\"",
                "close_issue": f"aiops issues close {issue.id}",
            },
        }

        # Step 3: Create branch if requested
        branch_name = None
        if create_branch:
            try:
                branch_prefix = issue_data.get("branch_prefix", "feature")
                branch_name = generate_branch_name(
                    issue.external_id, issue.title, branch_prefix
                )

                # Get user for git operations
                user = g.current_user if hasattr(g, "current_user") else None
                if user and user.linux_username:
                    checkout_or_create_branch(
                        project=project,
                        branch=branch_name,
                        base=project.default_branch,
                        user=user,
                    )
                    response_data["branch_name"] = branch_name
                else:
                    response_data["branch_warning"] = "Branch creation skipped: user not configured"
            except Exception as e:
                # Branch creation failed, but issue was created successfully
                response_data["branch_error"] = f"Failed to create branch: {e}"

        # Step 4: Start AI session if requested
        if start_session:
            try:
                from ...services.ai_session_service import save_session

                # Create session record
                session = save_session(
                    user_id=g.current_user.id if hasattr(g, "current_user") else None,
                    project_id=project_id,
                    issue_id=issue.id,
                    tool=ai_tool,
                    session_id=f"assisted-{issue.id}",
                    tmux_target=None,
                    description=f"AI-assisted work on issue #{issue.external_id}",
                )

                response_data["session_id"] = session.id
                response_data["session_url"] = f"/projects/{project_id}/ai?issue_id={issue.id}"
            except Exception as e:
                # Session creation failed, but issue was created successfully
                response_data["session_error"] = f"Failed to start session: {e}"

        return jsonify(response_data), 201

    except Exception as e:
        current_app.logger.exception("Unexpected error in create_assisted_issue")
        return jsonify({
            "error": "Unexpected error occurred",
            "details": str(e),
        }), 500


@api_v1_bp.post("/issues/<int:issue_id>/remap")
def remap_issue(issue_id: int):
    """Remap an issue to a different aiops project.

    This updates the internal aiops mapping only - the external issue tracker
    (GitHub/GitLab/Jira) remains unchanged.
    """
    from flask_login import current_user
    from sqlalchemy.exc import IntegrityError

    from ...services.activity_service import log_activity, ResourceType

    # Check admin status
    is_admin = False
    if hasattr(g, "api_user") and g.api_user:
        is_admin = getattr(g.api_user, "is_admin", False)
    elif current_user and current_user.is_authenticated:
        is_admin = getattr(current_user, "is_admin", False)

    if not is_admin:
        return jsonify({"error": "Admin access required to remap issues."}), 403

    # Get the issue
    issue = ExternalIssue.query.get_or_404(issue_id)

    # Get target project ID from request
    data = request.get_json(silent=True) or {}
    target_project_id = data.get("project_id")

    if not isinstance(target_project_id, int):
        return jsonify({"error": "project_id must be provided as an integer."}), 400

    # Get target project
    target_project = Project.query.get(target_project_id)
    if not target_project:
        return jsonify({"error": "Target project not found."}), 404

    # Get current integration and project
    old_project_integration = issue.project_integration
    old_project = old_project_integration.project if old_project_integration else None
    old_integration = old_project_integration.integration if old_project_integration else None

    # Check if the issue is already in the target project
    if old_project and old_project.id == target_project_id:
        return jsonify({"error": "Issue is already in the target project."}), 400

    # Find or create a ProjectIntegration for the target project with the same integration
    if not old_integration:
        return jsonify({"error": "Issue has no integration associated."}), 400

    target_project_integration = ProjectIntegration.query.filter_by(
        project_id=target_project_id,
        integration_id=old_integration.id
    ).first()

    if not target_project_integration:
        # Create a new ProjectIntegration
        # Use target project's repo URL or name as external identifier
        external_id = target_project.repo_url or target_project.name
        target_project_integration = ProjectIntegration(
            project_id=target_project_id,
            integration_id=old_integration.id,
            external_identifier=external_id
        )
        db.session.add(target_project_integration)
        db.session.flush()  # Get the ID without committing

    # Update the issue's project_integration_id
    old_project_integration_id = issue.project_integration_id
    issue.project_integration_id = target_project_integration.id

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        return jsonify({"error": f"Failed to remap issue: {exc}"}), 400

    # Log the remapping activity
    api_user_id = g.api_user.id if hasattr(g, "api_user") and g.api_user else None
    user_agent = request.headers.get("User-Agent", "").lower()
    source = "cli" if any(x in user_agent for x in ["python", "requests", "curl", "httpx"]) else "web"

    log_activity(
        action_type="issue.remap",
        user_id=api_user_id,
        resource_type=ResourceType.PROJECT,
        resource_id=target_project.id,
        resource_name=target_project.name,
        status="success",
        description=f"Remapped issue #{issue.external_id} from {old_project.name if old_project else 'unknown'} to {target_project.name}",
        extra_data={
            "issue_id": issue.id,
            "external_id": issue.external_id,
            "old_project_id": old_project.id if old_project else None,
            "old_project_name": old_project.name if old_project else None,
            "new_project_id": target_project.id,
            "new_project_name": target_project.name,
            "old_project_integration_id": old_project_integration_id,
            "new_project_integration_id": target_project_integration.id,
        },
        source=source,
    )

    return jsonify({
        "success": True,
        "issue": _issue_to_dict(issue),
        "message": f"Issue #{issue.external_id} remapped to project {target_project.name}"
    }), 200
