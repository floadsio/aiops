from __future__ import annotations

from datetime import datetime, timezone
import shlex
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable

from ..models import ExternalIssue, Project, User
from .issues.utils import format_issue_datetime, summarize_issue


BASE_CONTEXT_FILENAME = "AGENTS.md"
DEFAULT_CONTEXT_FILENAME = "AGENTS.override.md"
DEFAULT_TRACKED_CONTEXT_FILENAME = "AGENTS.override.md"
ISSUE_CONTEXT_START = "<!-- issue-context:start -->"
ISSUE_CONTEXT_END = "<!-- issue-context:end -->"
ISSUE_CONTEXT_SECTION_TITLE = "## Current Issue Context"
MISSING_ISSUE_DETAILS_MESSAGE = "No additional details provided by the issue tracker."


def _apply_atlassian_marks(text: str, marks: list[Any] | None) -> str:
    """Render Atlassian document format marks into Markdown."""
    if not marks:
        return text
    rendered = text
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mark_type = mark.get("type")
        if mark_type == "code":
            rendered = f"`{rendered}`"
        elif mark_type == "strong":
            rendered = f"**{rendered}**"
        elif mark_type == "em":
            rendered = f"*{rendered}*"
        elif mark_type == "strike":
            rendered = f"~~{rendered}~~"
        elif mark_type == "link":
            href = mark.get("attrs", {}).get("href")
            if href:
                rendered = f"[{rendered}]({href})"
    return rendered


def _render_atlassian_document(node: Any) -> str:
    """Convert Atlassian document format payloads to readable Markdown."""

    def render(current: Any) -> list[str]:
        if isinstance(current, dict):
            node_type = current.get("type")
            if node_type == "text":
                return [flatten_inline(current)]
            content = current.get("content", [])
            if node_type == "doc":
                lines: list[str] = []
                for child in content:
                    lines.extend(render(child))
                return lines
            if node_type == "paragraph":
                text = "".join(flatten_inline(child) for child in content).strip()
                return [text] if text else []
            if node_type == "heading":
                level = current.get("attrs", {}).get("level", 1)
                if not isinstance(level, int):
                    level = 1
                level = max(1, min(level, 6))
                text = "".join(flatten_inline(child) for child in content).strip()
                return [f"{'#' * level} {text}"] if text else []
            if node_type == "bulletList":
                lines: list[str] = []
                for item in content:
                    item_lines = render(item)
                    if not item_lines:
                        continue
                    first, *rest = item_lines
                    lines.append(f"- {first}")
                    lines.extend(f"  {line}" for line in rest if line)
                return lines
            if node_type == "orderedList":
                lines: list[str] = []
                start = current.get("attrs", {}).get("order", 1)
                if not isinstance(start, int):
                    start = 1
                counter = start
                for item in content:
                    item_lines = render(item)
                    if not item_lines:
                        continue
                    first, *rest = item_lines
                    lines.append(f"{counter}. {first}")
                    lines.extend(f"   {line}" for line in rest if line)
                    counter += 1
                return lines
            if node_type == "listItem":
                lines: list[str] = []
                for child in content:
                    lines.extend(render(child))
                return lines
            if node_type == "codeBlock":
                language = current.get("attrs", {}).get("language")
                body_lines: list[str] = []
                for child in content:
                    body_lines.extend(render(child))
                body = "\n".join(body_lines)
                fence = "```"
                if language:
                    return [f"{fence}{language}", body, fence]
                return [fence, body, fence]
            if node_type == "blockquote":
                lines: list[str] = []
                for child in content:
                    child_lines = render(child)
                    for line in child_lines:
                        prefix = "> " if line else ">"
                        lines.append(f"{prefix}{line}" if line else prefix.rstrip())
                return lines
            if node_type == "rule":
                return ["---"]
            if node_type == "panel":
                lines: list[str] = []
                for child in content:
                    lines.extend(render(child))
                return lines
            if node_type == "hardBreak":
                return [""]
            # Fallback: render nested content without additional formatting.
            lines: list[str] = []
            for child in content:
                lines.extend(render(child))
            return lines
        if isinstance(current, list):
            lines: list[str] = []
            for child in current:
                lines.extend(render(child))
            return lines
        if isinstance(current, str):
            return [current]
        return []

    def flatten_inline(current: Any) -> str:
        if isinstance(current, dict):
            node_type = current.get("type")
            if node_type == "text":
                text = current.get("text", "") or ""
                return _apply_atlassian_marks(text, current.get("marks"))
            if node_type == "hardBreak":
                return "\n"
            if node_type == "inlineCard":
                url = current.get("attrs", {}).get("url")
                return url or ""
            if node_type == "emoji":
                attrs = current.get("attrs", {}) or {}
                return attrs.get("text") or attrs.get("shortName") or ""
            if node_type == "mention":
                attrs = current.get("attrs", {}) or {}
                return attrs.get("text") or attrs.get("displayName") or ""
            content = current.get("content", [])
            return "".join(flatten_inline(child) for child in content)
        if isinstance(current, list):
            return "".join(flatten_inline(child) for child in current)
        if isinstance(current, str):
            return current
        return ""

    raw_lines = render(node)
    cleaned_lines: list[str] = []
    previous_blank = False
    for line in raw_lines:
        normalized = (line or "").rstrip()
        if not normalized:
            if not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue
        cleaned_lines.append(normalized)
        previous_blank = False
    return "\n".join(cleaned_lines).strip()


def _normalize_text_value(value: Any, *, allow_atlassian_document: bool = False) -> str | None:
    """Coerce provider payload fields into Markdown text."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip("\n")
        return text.strip() or None
    if allow_atlassian_document and isinstance(value, dict) and value.get("type") == "doc":
        rendered = _render_atlassian_document(value)
        return rendered or None
    if isinstance(value, dict):
        if allow_atlassian_document and value.get("type") == "doc":
            rendered = _render_atlassian_document(value)
            return rendered or None
        for candidate in ("text", "body", "description", "value"):
            if candidate in value:
                text = _normalize_text_value(
                    value.get(candidate),
                    allow_atlassian_document=allow_atlassian_document,
                )
                if text:
                    return text
        if "content" in value:
            text = _normalize_text_value(
                value.get("content"),
                allow_atlassian_document=allow_atlassian_document,
            )
            if text:
                return text
        return None
    if isinstance(value, list):
        parts = [
            _normalize_text_value(item, allow_atlassian_document=allow_atlassian_document)
            for item in value
        ]
        joined = "\n".join(part for part in parts if part)
        if not joined:
            return None
        stripped = joined.strip()
        return stripped or None
    return None


def _search_nested_text(source: Any, *, keywords: tuple[str, ...] = ("description", "body")) -> str | None:
    """Search nested payload structures for text fields that match known keywords."""
    if isinstance(source, dict):
        for key, value in source.items():
            lowercase_key = key.lower()
            allow_doc = "description" in lowercase_key
            if any(keyword in lowercase_key for keyword in keywords):
                text = _normalize_text_value(value, allow_atlassian_document=allow_doc)
                if text:
                    return text
        for value in source.values():
            nested = _search_nested_text(value, keywords=keywords)
            if nested:
                return nested
    elif isinstance(source, list):
        for item in source:
            nested = _search_nested_text(item, keywords=keywords)
            if nested:
                return nested
    return None


def _extract_issue_description(issue: ExternalIssue, provider: str | None) -> str | None:
    """Pull a human-readable issue description from stored payload metadata."""
    payload = issue.raw_payload or {}
    if not payload:
        return None

    provider_key = (provider or "").lower()
    if provider_key == "github":
        return _normalize_text_value(payload.get("body"))
    if provider_key == "gitlab":
        return _normalize_text_value(payload.get("description"))
    if provider_key == "jira":
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        description = _normalize_text_value(fields.get("description"), allow_atlassian_document=True)
        if description:
            return description
        rendered_fields = payload.get("renderedFields") if isinstance(payload.get("renderedFields"), dict) else {}
        rendered_description = _normalize_text_value(rendered_fields.get("description"))
        if rendered_description:
            return rendered_description
        return _search_nested_text(payload)

    for key in ("description", "body", "content", "details"):
        text = _normalize_text_value(payload.get(key))
        if text:
            return text

    return _search_nested_text(payload)


def render_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
    *,
    identity_user: User | None = None,
) -> str:
    """Build Markdown instructions for the selected issue, optionally including git identity guidance."""
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
    issue_description = _extract_issue_description(primary_issue, provider)

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

    details_section = (
        issue_description.strip()
        if issue_description
        else MISSING_ISSUE_DETAILS_MESSAGE
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

        ## Issue Description
        {details_section}

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
    git_identity_section = _render_git_identity_section(identity_user)
    if git_identity_section:
        content = f"{content}\n\n{git_identity_section.strip()}"
    return f"{content}\n"


def extract_issue_description(issue: ExternalIssue) -> str | None:
    """Return a Markdown-friendly description for the given issue, if available."""
    integration = (
        issue.project_integration.integration if issue.project_integration else None
    )
    provider = integration.provider if integration else None
    description = _extract_issue_description(issue, provider)
    if description is None:
        return None
    return description.strip() or None


def write_local_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
    filename: str = DEFAULT_CONTEXT_FILENAME,
    *,
    identity_user: User | None = None,
) -> Path:
    """Alias for tracked issue context writing (kept for compatibility)."""
    return write_tracked_issue_context(
        project,
        primary_issue,
        all_issues,
        filename=filename,
        identity_user=identity_user,
    )


def write_tracked_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
    filename: str = DEFAULT_TRACKED_CONTEXT_FILENAME,
    *,
    identity_user: User | None = None,
) -> Path:
    """Update a tracked AGENTS.override.md file with the latest context for the selected issue."""
    repo_path = Path(project.local_path)
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)

    context_path = repo_path / filename
    base_content = _load_base_instructions(repo_path)
    issue_content = render_issue_context(
        project,
        primary_issue,
        all_issues,
        identity_user=identity_user,
    ).rstrip()
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

    if stripped_existing:
        cleaned = _remove_existing_issue_context(stripped_existing)
    else:
        cleaned = ""

    cleaned_without_base = _strip_base_instructions(cleaned, base_content)

    sections: list[str] = []
    if base_content:
        sections.append(base_content.rstrip())
    if cleaned_without_base:
        sections.append(cleaned_without_base.rstrip())
    sections.append(appended_section.rstrip())

    updated = "\n\n---\n\n".join(section for section in sections if section)

    context_path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return context_path


def _render_git_identity_section(identity_user: User | None) -> str:
    """Return a Markdown section describing the git identity to use."""
    if identity_user is None:
        return ""
    name = (getattr(identity_user, "name", "") or "").strip()
    email = (getattr(identity_user, "email", "") or "").strip()
    if not name and not email:
        return ""

    details: list[str] = []
    if name:
        details.append(f"- Name: {name}")
    if email:
        details.append(f"- Email: {email}")

    setup_commands: list[str] = []
    env_commands: list[str] = []
    if name:
        quoted_name = shlex.quote(name)
        setup_commands.append(f"git config user.name {quoted_name}")
        env_commands.extend(
            [
                f"export GIT_AUTHOR_NAME={quoted_name}",
                f"export GIT_COMMITTER_NAME={quoted_name}",
            ]
        )
    if email:
        quoted_email = shlex.quote(email)
        setup_commands.append(f"git config user.email {quoted_email}")
        env_commands.extend(
            [
                f"export GIT_AUTHOR_EMAIL={quoted_email}",
                f"export GIT_COMMITTER_EMAIL={quoted_email}",
            ]
        )

    commands: list[str] = []
    if setup_commands:
        commands.extend(setup_commands)
    if env_commands:
        if commands:
            commands.append("")
        commands.extend(env_commands)

    command_block = ""
    if commands:
        command_block = f"```bash\n" + "\n".join(commands) + "\n```"

    section = dedent(
        f"""
        ## Git Identity
        Use this identity for commits created while working on this issue.

        {'\n'.join(details)}

        {command_block}
        """
    ).strip()
    return section


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


def _load_base_instructions(repo_path: Path) -> str:
    base_path = repo_path / BASE_CONTEXT_FILENAME
    if not base_path.exists():
        return ""
    raw = base_path.read_text(encoding="utf-8").rstrip()
    return _remove_existing_issue_context(raw)


def _strip_base_instructions(source: str, base_content: str) -> str:
    if not source:
        return ""
    stripped_source = source.strip()
    if not base_content:
        return stripped_source
    normalized_base = base_content.strip()
    if not normalized_base:
        return stripped_source

    if stripped_source.startswith(normalized_base):
        remainder = stripped_source[len(normalized_base):].lstrip()
        if remainder.startswith("---"):
            remainder = remainder[3:].lstrip("- \n")
        return remainder.lstrip()

    return stripped_source
