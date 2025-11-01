from __future__ import annotations

from datetime import datetime, timezone

from ...models import ExternalIssue


def format_issue_datetime(value: datetime | None) -> str:
    """Format timestamps for human-readable displays."""
    if value is None:
        return "Unknown"
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def summarize_issue(issue: ExternalIssue, include_url: bool = False) -> str:
    """Build a compact summary string for listing issues."""
    integration = (
        issue.project_integration.integration if issue.project_integration else None
    )
    provider = integration.provider if integration else "unknown"
    parts = [f"[{provider}] {issue.external_id}: {issue.title}"]
    parts.append(f"status={issue.status or 'unspecified'}")
    if issue.assignee:
        parts.append(f"assignee={issue.assignee}")
    if issue.labels:
        parts.append(f"labels={', '.join(issue.labels)}")
    parts.append(
        f"updated={format_issue_datetime(issue.external_updated_at or issue.updated_at or issue.created_at)}"
    )
    if include_url and issue.url:
        parts.append(f"url={issue.url}")
    return "; ".join(parts)
