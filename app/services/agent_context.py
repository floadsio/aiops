from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Iterable

from ..models import ExternalIssue, Project
from .issues.utils import format_issue_datetime, summarize_issue


DEFAULT_CONTEXT_FILENAME = "AGENTS.md"
DEFAULT_TRACKED_CONTEXT_FILENAME = "AGENTS.md"
ISSUE_CONTEXT_START = "<!-- issue-context:start -->"
ISSUE_CONTEXT_END = "<!-- issue-context:end -->"
ISSUE_CONTEXT_SECTION_TITLE = "## Current Issue Context"


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
    """Alias for tracked issue context writing (kept for compatibility)."""
    return write_tracked_issue_context(
        project,
        primary_issue,
        all_issues,
        filename=filename,
    )


def write_tracked_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
    filename: str = DEFAULT_TRACKED_CONTEXT_FILENAME,
) -> Path:
    """Update a tracked AGENTS.md file with the latest context for the selected issue."""
    repo_path = Path(project.local_path)
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)

    context_path = repo_path / filename
    issue_content = render_issue_context(project, primary_issue, all_issues).rstrip()
    header_note = "NOTE: Generated issue context. Update before publishing if needed."
    appended_section = (
        f"{ISSUE_CONTEXT_SECTION_TITLE}\n"
        f"{ISSUE_CONTEXT_START}\n\n"
        f"{header_note}\n\n"
        f"{issue_content}\n"
        f"{ISSUE_CONTEXT_END}"
    )

    existing = ""
    if context_path.exists():
        existing = context_path.read_text(encoding="utf-8")
        stripped_existing = existing.rstrip()
    else:
        stripped_existing = ""

    if existing:
        cleaned = _remove_existing_issue_context(stripped_existing)
    else:
        cleaned = stripped_existing

    if cleaned:
        updated = f"{cleaned.rstrip()}\n\n{appended_section}"
    else:
        updated = appended_section

    context_path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return context_path


def _remove_existing_issue_context(source: str) -> str:
    """Strip any previously appended issue context block while keeping project docs intact."""
    if ISSUE_CONTEXT_START not in source or ISSUE_CONTEXT_END not in source:
        return source

    start_index = source.find(ISSUE_CONTEXT_START)
    end_index = source.find(ISSUE_CONTEXT_END, start_index)
    if start_index == -1 or end_index == -1:
        return source

    end_index += len(ISSUE_CONTEXT_END)
    prefix = source[:start_index]
    suffix = source[end_index:]

    # Remove trailing section title if it directly precedes the marker block.
    title_index = prefix.rfind(ISSUE_CONTEXT_SECTION_TITLE)
    if title_index != -1 and prefix[title_index:].strip().startswith(ISSUE_CONTEXT_SECTION_TITLE):
        prefix = prefix[:title_index]

    cleaned_prefix = prefix.rstrip()
    cleaned_suffix = suffix.lstrip()
    if cleaned_prefix and cleaned_suffix:
        return f"{cleaned_prefix}\n\n{cleaned_suffix}"
    return cleaned_prefix or cleaned_suffix
