"""API v1 issue management endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import current_app, g, jsonify, request
from sqlalchemy.orm import selectinload

from ...extensions import db
from ...models import ExternalIssue, Project, ProjectIntegration, TenantIntegration
from ...services.api_auth import audit_api_request, require_api_auth
from ...services.issues.github import GitHubIssueProvider  # type: ignore
from ...services.issues.gitlab import GitLabIssueProvider  # type: ignore
from ...services.issues.jira import JiraIssueProvider  # type: ignore
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
        if assignee and issue_payload.get("assignee") != assignee:
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

    # Map assignee to provider-specific identity if provided
    assignee_identity = None
    if assignee_username:
        identity_map = get_user_identity(user.id)
        if identity_map:
            provider = integration.provider.lower()
            if provider == "github":
                assignee_identity = identity_map.github_username
            elif provider == "gitlab":
                assignee_identity = identity_map.gitlab_username
            elif provider == "jira":
                assignee_identity = identity_map.jira_account_id

    # Create issue via provider
    try:
        provider = _get_issue_provider(integration)
        external_issue_data = provider.create_issue(
            project_integration=project_integration,
            title=title,
            description=description or "",
            labels=labels,
            assignee=assignee_identity,
        )
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

    try:
        provider = _get_issue_provider(integration)
        comment_data = provider.add_comment(
            project_integration=issue.project_integration,
            issue_number=issue.external_id,
            body=body,
        )
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
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to assign issue: %s", exc)
        return jsonify({"error": f"Failed to assign issue: {str(exc)}"}), 500

    # Update local assignee
    issue.assignee = assignee
    issue.last_seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"issue": _issue_to_dict(issue)})
