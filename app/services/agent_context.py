from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Iterable

from ..models import ExternalIssue, Project
from .issues.utils import format_issue_datetime, summarize_issue


DEFAULT_CONTEXT_FILENAME = "AGENTS.local.md"


def render_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
) -> str:
    """Build Markdown instructions for the selected issue."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    integration = (
        primary_issue.project_integration.integration
        if primary_issue.project_integration
        else None
    )
    provider = integration.provider if integration else "unknown"
    other_issues = [
        issue for issue in all_issues if issue.id != primary_issue.id
    ]

    other_issues_section = "\n".join(
        f"- {summarize_issue(issue, include_url=True)}" for issue in other_issues
    ) or "None listed."

    labels = ", ".join(primary_issue.labels) if primary_issue.labels else "none"
    assignee = primary_issue.assignee or "unassigned"
    status = primary_issue.status or "unspecified"
    source_url = primary_issue.url or "N/A"
    last_updated = format_issue_datetime(
        primary_issue.external_updated_at
        or primary_issue.updated_at
        or primary_issue.created_at
    )

    content = dedent(
        f"""
        # {primary_issue.external_id} - {primary_issue.title}

        _Updated: {timestamp}_

        ## Issue Snapshot
        - Provider: {provider}
        - Status: {status}
        - Assignee: {assignee}
        - Labels: {labels}
        - Source: {source_url}
        - Last Synced: {last_updated}

        ## Project Context
        - Project: {project.name}
        - Repository: {project.repo_url}
        - Local Path: {project.local_path}

        ## Other Known Issues
        {other_issues_section}

        ## Workflow Reminders
        1. Confirm the acceptance criteria with the external issue tracker.
        2. Explore relevant code paths and recent history.
        3. Draft a short execution plan before editing files.
        4. Implement changes with tests or validation steps.
        5. Summarize modifications and verification commands when you finish.
        """
    ).strip()
    return content + "\n"


def write_local_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
    filename: str = DEFAULT_CONTEXT_FILENAME,
) -> Path:
    """Write the issue context Markdown file inside the project checkout."""
    repo_path = Path(project.local_path)
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)

    context_path = repo_path / filename
    content = render_issue_context(project, primary_issue, all_issues)
    context_path.write_text(content, encoding="utf-8")
    return context_path
