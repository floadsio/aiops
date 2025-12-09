"""API v1 communications endpoints - central hub for all issue comments."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import current_app, jsonify, request
from sqlalchemy import desc, func
from sqlalchemy.orm import selectinload

from ...models import (
    ExternalIssue,
    Project,
    ProjectIntegration,
    UserIdentityMap,
)
from ...services.api_auth import audit_api_request, require_api_auth
from ...services.issues.utils import normalize_issue_status
from ...utils.text_rendering import render_issue_rich_text
from . import api_v1_bp


def _serialize_timestamp(value: datetime | None) -> str | None:
    """Convert datetime to ISO format string."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _map_comment_author(
    author_name: str,
    integration_id: int,
    provider: str,
) -> dict[str, Any]:
    """Map a remote author to local user if available.

    Args:
        author_name: Remote username/author name
        integration_id: Integration ID for credential lookup
        provider: Provider type (github, gitlab, jira)

    Returns:
        dict with author info including local user mapping if available
    """
    author_info = {
        "remote_name": author_name,
        "display_name": author_name,
        "local_user_id": None,
        "local_user_name": None,
    }

    if not author_name:
        return author_info

    # Map remote username to local user via UserIdentityMap
    provider_lower = provider.lower()
    identity_filter = None

    if provider_lower == "github":
        identity_filter = UserIdentityMap.github_username == author_name
    elif provider_lower == "gitlab":
        identity_filter = UserIdentityMap.gitlab_username == author_name
    elif provider_lower == "jira":
        identity_filter = UserIdentityMap.jira_account_id == author_name

    if identity_filter is not None:
        try:
            identity_map = UserIdentityMap.query.filter(identity_filter).first()
            if identity_map and identity_map.user:
                author_info["local_user_id"] = identity_map.user_id
                author_info["local_user_name"] = identity_map.user.name or identity_map.user.email
                author_info["display_name"] = author_info["local_user_name"]
        except Exception:  # noqa: BLE001
            # If mapping fails, just use remote name
            pass

    return author_info


def _get_issue_body(issue: ExternalIssue) -> tuple[str, str]:
    """Extract issue body/description from raw payload.

    Args:
        issue: The external issue

    Returns:
        Tuple of (raw_body, rendered_html)
    """
    # Try to extract body from raw_payload
    body = ""
    body_html = ""

    if issue.raw_payload and isinstance(issue.raw_payload, dict):
        # Check for Jira pre-rendered HTML first (includes proper attachment URLs)
        rendered_fields = issue.raw_payload.get("renderedFields")
        if rendered_fields and isinstance(rendered_fields, dict):
            body_html = rendered_fields.get("description")

        # GitHub, GitLab use "body" at top level
        body = issue.raw_payload.get("body")

        # GitLab/general description field
        if not body:
            body = issue.raw_payload.get("description")

        # Jira stores it nested under fields.description
        if not body and "fields" in issue.raw_payload:
            fields = issue.raw_payload.get("fields", {})
            if isinstance(fields, dict):
                body = fields.get("description")

        # Alternative field names
        if not body:
            body = issue.raw_payload.get("body_text")
        if not body:
            body = issue.raw_payload.get("summary")

        # Convert to string if not already (some APIs return None/null)
        if body and body != "null":
            body = str(body).strip() if body else ""
        else:
            body = ""

    if not body:
        return "", ""

    # Use pre-rendered HTML if available (Jira provides this with proper attachment URLs)
    # Otherwise render the body content ourselves
    if body_html:
        # Sanitize the Jira HTML to ensure it's safe
        from app.template_utils import sanitize_html
        rendered_body = sanitize_html(body_html)

        # Convert relative Jira attachment URLs to use our proxy
        # Jira provides relative URLs like /rest/api/3/attachment/content/12345
        # We proxy them to avoid CORS and authentication issues
        integration = issue.project_integration.integration
        if integration and integration.provider.lower() == "jira":
            # Replace Jira URLs with our proxy endpoint
            rendered_body_str = str(rendered_body)
            # Match: src="/rest/api/... or src="https://jira.../rest/api/...
            import re
            def replace_jira_url(match):
                url = match.group(1)
                # Extract the path part (everything after the domain if present)
                if url.startswith('http'):
                    # Extract path from absolute URL
                    path_match = re.search(r'(\/rest\/api\/.+)', url)
                    if path_match:
                        path = path_match.group(1)
                    else:
                        return match.group(0)  # Keep original if can't parse
                else:
                    # Already a relative path
                    path = url
                # Build proxy URL
                proxy_url = f"/api/v1/jira/attachment/{integration.id}{path}"
                return f'src="{proxy_url}"'

            rendered_body_str = re.sub(
                r'src="([^"]*\/rest\/api\/[^"]+)"',
                replace_jira_url,
                rendered_body_str
            )
            from markupsafe import Markup
            rendered_body = Markup(rendered_body_str)
    else:
        # Render the body content (handles markdown for GitHub/GitLab, Jira syntax, HTML, etc.)
        rendered_body = render_issue_rich_text(body)

    return body, str(rendered_body)


def _comment_to_dict(
    comment: dict[str, Any],
    issue: ExternalIssue,
) -> dict[str, Any]:
    """Convert a comment dict to API response format.

    Args:
        comment: Comment data from issue.comments
        issue: The external issue containing the comment

    Returns:
        Formatted comment dict with author mapping and rendered HTML
    """
    integration = issue.project_integration.integration
    author = comment.get("author", "Unknown")
    body = comment.get("body", "")

    # Use pre-rendered HTML if available (Jira, GitHub provide this), otherwise render it
    body_html = comment.get("body_html")
    if not body_html:
        # Render the body content (handles markdown for GitHub/GitLab, Jira syntax, etc.)
        rendered_body = render_issue_rich_text(body)
        body_html = str(rendered_body)
    elif integration and integration.provider.lower() == "jira":
        # Convert Jira attachment URLs to use our proxy
        if 'src="/rest/api/' in body_html or '/rest/api/' in body_html:
            import re
            def replace_jira_url(match):
                url = match.group(1)
                # Extract the path part
                if url.startswith('http'):
                    path_match = re.search(r'(\/rest\/api\/.+)', url)
                    if path_match:
                        path = path_match.group(1)
                    else:
                        return match.group(0)
                else:
                    path = url
                proxy_url = f"/api/v1/jira/attachment/{integration.id}{path}"
                return f'src="{proxy_url}"'

            body_html = re.sub(
                r'src="([^"]*\/rest\/api\/[^"]+)"',
                replace_jira_url,
                body_html
            )

    return {
        "id": comment.get("id"),
        "author": _map_comment_author(
            author,
            integration.id,
            integration.provider.lower(),
        ),
        "body": body,
        "body_html": body_html,  # Pre-rendered HTML for display
        "created_at": comment.get("created_at"),
        "url": comment.get("url"),
    }


@api_v1_bp.get("/communications")
@require_api_auth(scopes=["read"])
@audit_api_request
def get_communications():
    """Get all comments from all issues across all projects/tenants.

    Query Parameters:
        tenant_id (int, optional): Filter by tenant
        project_id (int, optional): Filter by project
        user_id (int, optional): Filter comments by author (local user mapping)
        limit (int, default=100): Number of comments to return
        offset (int, default=0): Pagination offset
        sort (str, default='recent'): Sort order (recent, oldest, updated)

    Returns:
        200: List of comments with thread context
    """
    try:
        # Get query parameters
        tenant_id = request.args.get("tenant_id", type=int)
        project_id = request.args.get("project_id", type=int)
        limit = request.args.get("limit", default=100, type=int)
        offset = request.args.get("offset", default=0, type=int)
        sort_by = request.args.get("sort", default="recent")

        # Validate pagination
        limit = min(limit, 500)  # Max 500 comments per request
        if limit < 1:
            limit = 100
        if offset < 0:
            offset = 0

        # Build query
        query = ExternalIssue.query.options(
            selectinload(ExternalIssue.project_integration).selectinload(
                ProjectIntegration.integration
            ),
            selectinload(ExternalIssue.project_integration).selectinload(
                ProjectIntegration.project
            ).selectinload(Project.tenant),
        )

        # Apply filters - handle joins to avoid duplicates
        if tenant_id or project_id:
            query = query.join(ProjectIntegration)
            if tenant_id:
                query = query.join(Project).filter(Project.tenant_id == tenant_id)
            if project_id:
                query = query.filter(ProjectIntegration.project_id == project_id)

        # Only include issues with comments
        query = query.filter(func.json_array_length(ExternalIssue.comments) > 0)

        # Apply sorting
        if sort_by == "oldest":
            query = query.order_by(ExternalIssue.created_at)
        else:  # Default to recent
            query = query.order_by(desc(ExternalIssue.external_updated_at or ExternalIssue.created_at))

        # Get total count before pagination
        total_count = query.count()

        # Apply pagination
        issues = query.limit(limit).offset(offset).all()

        # Build response - flatten comments with issue context
        communications = []
        for issue in issues:
            integration = issue.project_integration.integration
            project = issue.project_integration.project
            tenant = project.tenant if project else None
            status_key, status_label = normalize_issue_status(issue.status)

            comments = issue.comments or []
            for comment in comments:
                communications.append({
                    "issue_id": issue.id,
                    "issue_external_id": issue.external_id,
                    "issue_title": issue.title,
                    "issue_status": issue.status,
                    "issue_status_key": status_key,
                    "issue_status_label": status_label,
                    "issue_url": issue.url,
                    "issue_assignee": issue.assignee,
                    "comment": _comment_to_dict(comment, issue),
                    "provider": integration.provider.lower() if integration else None,
                    "provider_name": integration.provider if integration else None,
                    "integration_id": integration.id if integration else None,
                    "integration_name": integration.name if integration else None,
                    "project_id": project.id if project else None,
                    "project_name": project.name if project else None,
                    "tenant_id": tenant.id if tenant else None,
                    "tenant_name": tenant.name if tenant else None,
                })

        return jsonify({
            "communications": communications,
            "pagination": {
                "total": total_count,
                "count": len(communications),
                "limit": limit,
                "offset": offset,
            },
        })

    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to fetch communications: %s", exc)
        return jsonify({"error": f"Failed to fetch communications: {str(exc)}"}), 500


@api_v1_bp.get("/communications/threads")
@require_api_auth(scopes=["read"])
@audit_api_request
def get_communication_threads():
    """Get comments grouped by issue (thread view).

    Query Parameters:
        tenant_id (int, optional): Filter by tenant
        project_id (int, optional): Filter by project
        limit (int, default=50): Number of threads to return
        offset (int, default=0): Pagination offset

    Returns:
        200: List of issue threads with comments
    """
    try:
        # Get query parameters
        tenant_id = request.args.get("tenant_id", type=int)
        project_id = request.args.get("project_id", type=int)
        issue_id = request.args.get("issue_id", type=int)
        limit = request.args.get("limit", default=50, type=int)
        offset = request.args.get("offset", default=0, type=int)

        # Validate pagination
        limit = min(limit, 200)  # Max 200 threads per request
        if limit < 1:
            limit = 50
        if offset < 0:
            offset = 0

        # Build query
        query = ExternalIssue.query.options(
            selectinload(ExternalIssue.project_integration).selectinload(
                ProjectIntegration.integration
            ),
            selectinload(ExternalIssue.project_integration).selectinload(
                ProjectIntegration.project
            ).selectinload(Project.tenant),
        )

        # Apply filters - handle joins to avoid duplicates
        if tenant_id or project_id:
            query = query.join(ProjectIntegration)
            if tenant_id:
                query = query.join(Project).filter(Project.tenant_id == tenant_id)
            if project_id:
                query = query.filter(ProjectIntegration.project_id == project_id)

        # Filter by specific issue ID (for deep linking from pinned comments)
        if issue_id:
            query = query.filter(ExternalIssue.id == issue_id)

        # Only include issues with comments
        query = query.filter(func.json_array_length(ExternalIssue.comments) > 0)

        # Sort by most recently updated
        query = query.order_by(
            desc(ExternalIssue.external_updated_at or ExternalIssue.created_at)
        )

        # Get total count before pagination
        total_count = query.count()

        # Apply pagination
        issues = query.limit(limit).offset(offset).all()

        # Build thread response
        threads = []
        for issue in issues:
            integration = issue.project_integration.integration
            project = issue.project_integration.project
            tenant = project.tenant if project else None
            status_key, status_label = normalize_issue_status(issue.status)

            comments = issue.comments or []
            issue_body, issue_body_html = _get_issue_body(issue)

            threads.append({
                "issue_id": issue.id,
                "issue_external_id": issue.external_id,
                "issue_title": issue.title,
                "issue_body": issue_body,
                "issue_body_html": issue_body_html,
                "issue_status": issue.status,
                "issue_status_key": status_key,
                "issue_status_label": status_label,
                "issue_url": issue.url,
                "issue_assignee": issue.assignee,
                "issue_labels": issue.labels or [],
                "provider": integration.provider.lower() if integration else None,
                "provider_name": integration.provider if integration else None,
                "integration_id": integration.id if integration else None,
                "integration_name": integration.name if integration else None,
                "project_id": project.id if project else None,
                "project_name": project.name if project else None,
                "tenant_id": tenant.id if tenant else None,
                "tenant_name": tenant.name if tenant else None,
                "comment_count": len(comments),
                "comments": [_comment_to_dict(c, issue) for c in comments],
                "created_at": _serialize_timestamp(issue.created_at),
                "updated_at": _serialize_timestamp(
                    issue.external_updated_at or issue.updated_at or issue.created_at
                ),
            })

        return jsonify({
            "threads": threads,
            "pagination": {
                "total": total_count,
                "count": len(threads),
                "limit": limit,
                "offset": offset,
            },
        })

    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to fetch communication threads: %s", exc)
        return jsonify({
            "error": f"Failed to fetch communication threads: {str(exc)}"
        }), 500
