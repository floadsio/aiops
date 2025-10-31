from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

from flask import current_app

from ...models import ExternalIssue, Project


def _ensure_agent_directory(base_path: Path) -> Path:
    base_path.mkdir(parents=True, exist_ok=True)
    return base_path


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Unknown"
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _summarize_issue(issue: ExternalIssue, include_url: bool = False) -> str:
    integration = issue.project_integration.integration if issue.project_integration else None
    provider = integration.provider if integration else "unknown"
    parts = [f"[{provider}] {issue.external_id}: {issue.title}"]
    parts.append(f"status={issue.status or 'unspecified'}")
    if issue.assignee:
        parts.append(f"assignee={issue.assignee}")
    if issue.labels:
        parts.append(f"labels={', '.join(issue.labels)}")
    parts.append(
        f"updated={_format_datetime(issue.external_updated_at or issue.updated_at or issue.created_at)}"
    )
    if include_url and issue.url:
        parts.append(f"url={issue.url}")
    return "; ".join(parts)


def build_issue_prompt(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: list[ExternalIssue],
) -> str:
    tenant = project.tenant
    lines = [
        f"Project: {project.name}",
        f"Tenant: {tenant.name if tenant else 'N/A'}",
        f"Repository: {project.repo_url}",
        f"Local Path: {project.local_path}",
        "",
        "== Selected Issue ==",
        _summarize_issue(primary_issue, include_url=True),
        "",
        "== All Project Issues ==",
    ]
    for issue in all_issues:
        prefix = "-> " if issue.id == primary_issue.id else "   "
        lines.append(prefix + _summarize_issue(issue))

    lines.extend(
        [
            "",
            "Focus on the selected issue (marked with ->).",
            "1. Review relevant code and history.",
            "2. Outline a plan before editing files.",
            "3. Implement changes and update/add tests.",
            "4. Summarize modifications and validation steps.",
        ]
    )
    return "\n".join(lines)


def build_issue_agent_file(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: list[ExternalIssue],
) -> Path:
    instance_path = Path(current_app.instance_path)
    agents_root = _ensure_agent_directory(instance_path / "agents" / f"project_{project.id}")
    filename = f"issue_{primary_issue.external_id}.md"
    agent_path = agents_root / filename

    integration = (
        primary_issue.project_integration.integration if primary_issue.project_integration else None
    )
    tenant = project.tenant

    issues_summary = "\n".join(
        f"* {'-> ' if issue.id == primary_issue.id else ''}{_summarize_issue(issue)}"
        for issue in all_issues
    )

    content = dedent(
        f"""
        # Agent: {primary_issue.title}

        ## Project Context
        - Project Name: {project.name}
        - Tenant: {tenant.name if tenant else 'N/A'}
        - Repository URL: {project.repo_url}
        - Local Path: {project.local_path}

        ## Selected Issue
        - Provider: {integration.provider if integration else 'unknown'}
        - Integration Name: {integration.name if integration else 'Unknown Integration'}
        - External ID: {primary_issue.external_id}
        - Status: {primary_issue.status or 'unspecified'}
        - Assignee: {primary_issue.assignee or 'unassigned'}
        - Labels: {', '.join(primary_issue.labels) if primary_issue.labels else 'none'}
        - Source URL: {primary_issue.url or 'N/A'}
        - Last Updated: {_format_datetime(primary_issue.external_updated_at or primary_issue.updated_at or primary_issue.created_at)}

        ## All Issues for this Project
        {issues_summary}

        ## Instructions
        1. Focus on the selected issue (marked with ->).
        2. Review related code and the overall issue list for context.
        3. Summarize an execution plan before editing files.
        4. Implement required changes and run tests or linters.
        5. Document the work performed and recommended validation steps.
        """
    ).strip()

    agent_path.write_text(content, encoding="utf-8")
    return agent_path
