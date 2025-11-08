from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from flask import current_app

from ...models import ExternalIssue, Project
from ..agent_context import write_local_issue_context
from .utils import format_issue_datetime, summarize_issue


def _ensure_agent_directory(base_path: Path) -> Path:
    base_path.mkdir(parents=True, exist_ok=True)
    return base_path


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
        summarize_issue(primary_issue, include_url=True),
        "",
        "== All Project Issues ==",
    ]
    for issue in all_issues:
        prefix = "-> " if issue.id == primary_issue.id else "   "
        lines.append(prefix + summarize_issue(issue))

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
        f"* {'-> ' if issue.id == primary_issue.id else ''}{summarize_issue(issue)}"
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
        - ID: {primary_issue.external_id}
        - Status: {primary_issue.status or 'unspecified'}
        - Assignee: {primary_issue.assignee or 'unassigned'}
        - Labels: {', '.join(primary_issue.labels) if primary_issue.labels else 'none'}
        - Source URL: {primary_issue.url or 'N/A'}
        - Last Updated: {format_issue_datetime(primary_issue.external_updated_at or primary_issue.updated_at or primary_issue.created_at)}

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

    # Maintain a git-ignored local context file for agent sessions.
    try:
        write_local_issue_context(project, primary_issue, all_issues)
    except Exception:  # pragma: no cover - best effort
        current_app.logger.exception("Failed to write local agent context")

    return agent_path
