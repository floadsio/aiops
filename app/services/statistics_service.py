"""Service for generating issue resolution statistics and workflow metrics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import ExternalIssue, Project, ProjectIntegration


def get_resolution_statistics(
    tenant_id: Optional[int] = None,
    project_id: Optional[int] = None,
    days: int = 30,
) -> dict[str, Any]:
    """Get statistics on resolved issues.

    Args:
        tenant_id: Filter by tenant (None for all)
        project_id: Filter by project (None for all)
        days: Number of days to look back

    Returns:
        Dictionary containing resolution statistics
    """
    # Base query for closed issues
    query = db.session.query(ExternalIssue).options(
        joinedload(ExternalIssue.project_integration).joinedload(
            ProjectIntegration.project
        )
    )

    # Apply filters
    if project_id:
        query = query.join(ProjectIntegration).filter(
            ProjectIntegration.project_id == project_id
        )
    elif tenant_id:
        query = query.join(ProjectIntegration).join(Project).filter(
            Project.tenant_id == tenant_id
        )

    # Filter by closed status and date range
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    query = query.filter(
        or_(
            ExternalIssue.status == "closed",
            ExternalIssue.status == "resolved",
            ExternalIssue.status == "done",
        ),
        ExternalIssue.updated_at >= cutoff_date,
    )

    resolved_issues = query.all()

    # Calculate statistics
    total_resolved = len(resolved_issues)
    resolution_times: list[float] = []
    project_breakdown: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "avg_resolution_time": 0}
    )

    for issue in resolved_issues:
        # Calculate resolution time
        if issue.created_at and issue.updated_at:
            resolution_time_seconds = (issue.updated_at - issue.created_at).total_seconds()
            resolution_time_hours = resolution_time_seconds / 3600
            resolution_times.append(resolution_time_hours)

            # Track by project
            project_name = (
                issue.project_integration.project.name
                if issue.project_integration and issue.project_integration.project
                else "Unknown"
            )
            project_breakdown[project_name]["count"] += 1

    # Calculate average resolution time
    avg_resolution_time = (
        sum(resolution_times) / len(resolution_times) if resolution_times else 0
    )

    # Calculate per-project averages
    for project_name in project_breakdown:
        project_issue_times = [
            rt
            for issue, rt in zip(resolved_issues, resolution_times, strict=False)
            if (
                issue.project_integration
                and issue.project_integration.project
                and issue.project_integration.project.name == project_name
            )
        ]
        if project_issue_times:
            project_breakdown[project_name]["avg_resolution_time"] = sum(
                project_issue_times
            ) / len(project_issue_times)

    return {
        "total_resolved": total_resolved,
        "avg_resolution_time_hours": round(avg_resolution_time, 2),
        "project_breakdown": dict(project_breakdown),
        "period_days": days,
    }


def get_workflow_statistics(
    tenant_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> dict[str, Any]:
    """Get workflow statistics including status distribution.

    Args:
        tenant_id: Filter by tenant (None for all)
        project_id: Filter by project (None for all)

    Returns:
        Dictionary containing workflow statistics
    """
    # Base query
    query = db.session.query(ExternalIssue).options(
        joinedload(ExternalIssue.project_integration).joinedload(
            ProjectIntegration.project
        )
    )

    # Apply filters
    if project_id:
        query = query.join(ProjectIntegration).filter(
            ProjectIntegration.project_id == project_id
        )
    elif tenant_id:
        query = query.join(ProjectIntegration).join(Project).filter(
            Project.tenant_id == tenant_id
        )

    all_issues = query.all()

    # Status distribution
    status_counts: dict[str, int] = defaultdict(int)
    for issue in all_issues:
        status = issue.status or "unknown"
        status_counts[status] += 1

    # Open vs closed
    open_statuses = {"open", "in_progress", "todo", "new", "reopened"}
    closed_statuses = {"closed", "resolved", "done"}

    open_count = sum(
        count for status, count in status_counts.items() if status in open_statuses
    )
    closed_count = sum(
        count for status, count in status_counts.items() if status in closed_statuses
    )
    other_count = sum(
        count
        for status, count in status_counts.items()
        if status not in open_statuses and status not in closed_statuses
    )

    return {
        "total_issues": len(all_issues),
        "open_count": open_count,
        "closed_count": closed_count,
        "other_count": other_count,
        "status_distribution": dict(status_counts),
    }


def get_contributor_statistics(
    tenant_id: Optional[int] = None,
    project_id: Optional[int] = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get statistics on who worked on which issues.

    Args:
        tenant_id: Filter by tenant (None for all)
        project_id: Filter by project (None for all)
        days: Number of days to look back

    Returns:
        List of contributor statistics
    """
    # Base query
    query = db.session.query(ExternalIssue).options(
        joinedload(ExternalIssue.project_integration).joinedload(
            ProjectIntegration.project
        )
    )

    # Apply filters
    if project_id:
        query = query.join(ProjectIntegration).filter(
            ProjectIntegration.project_id == project_id
        )
    elif tenant_id:
        query = query.join(ProjectIntegration).join(Project).filter(
            Project.tenant_id == tenant_id
        )

    # Filter by date range
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    query = query.filter(ExternalIssue.updated_at >= cutoff_date)

    issues = query.all()

    # Track contributor activity
    contributor_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"assigned_count": 0, "commented_count": 0, "issues": []}
    )

    for issue in issues:
        # Track assignee
        if issue.assignee:
            contributor_stats[issue.assignee]["assigned_count"] += 1
            contributor_stats[issue.assignee]["issues"].append(
                {
                    "id": issue.id,
                    "external_id": issue.external_id,
                    "title": issue.title,
                    "status": issue.status,
                    "url": issue.url,
                }
            )

        # Track commenters
        if issue.comments:
            commenters = set()
            for comment in issue.comments:
                if isinstance(comment, dict) and "author" in comment:
                    author = comment["author"]
                    if author and author not in commenters:
                        commenters.add(author)
                        contributor_stats[author]["commented_count"] += 1

    # Convert to list and sort by activity
    result = [
        {
            "contributor": name,
            "assigned_count": stats["assigned_count"],
            "commented_count": stats["commented_count"],
            "total_activity": stats["assigned_count"] + stats["commented_count"],
            "issues": stats["issues"][:5],  # Limit to 5 recent issues
        }
        for name, stats in contributor_stats.items()
    ]

    result.sort(key=lambda x: x["total_activity"], reverse=True)

    return result


def get_project_list(tenant_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Get list of projects for filtering.

    Args:
        tenant_id: Filter by tenant (None for all)

    Returns:
        List of projects with id and name
    """
    query = db.session.query(Project)

    if tenant_id:
        query = query.filter(Project.tenant_id == tenant_id)

    projects = query.order_by(Project.name).all()

    return [{"id": p.id, "name": p.name, "tenant_name": p.tenant.name} for p in projects]
