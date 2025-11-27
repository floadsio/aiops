from __future__ import annotations

import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable

from ..models import ExternalIssue, Project, User
from .issues.utils import format_issue_datetime, summarize_issue
from .sudo_service import SudoError, run_as_user, test_path
from .workspace_service import get_workspace_path, resolve_linux_username

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

    def render(current: Any) -> Iterable[str]:
        if isinstance(current, dict):
            node_type = current.get("type")
            if node_type == "text":
                yield flatten_inline(current)
                return
            content = current.get("content", [])
            if node_type == "doc":
                for child in content:
                    yield from render(child)
                return
            if node_type == "paragraph":
                text = "".join(flatten_inline(child) for child in content).strip()
                if text:
                    yield text
                return
            if node_type == "heading":
                level = current.get("attrs", {}).get("level", 1)
                if not isinstance(level, int):
                    level = 1
                level = max(1, min(level, 6))
                text = "".join(flatten_inline(child) for child in content).strip()
                if text:
                    yield f"{'#' * level} {text}"
                return
            if node_type == "bulletList":
                for item in content:
                    item_lines = list(render(item))
                    if not item_lines:
                        continue
                    first, *rest = item_lines
                    yield f"- {first}"
                    for line in rest:
                        if line:
                            yield f"  {line}"
                return
            if node_type == "orderedList":
                start = current.get("attrs", {}).get("order", 1)
                if not isinstance(start, int):
                    start = 1
                counter = start
                for item in content:
                    item_lines = list(render(item))
                    if not item_lines:
                        continue
                    first, *rest = item_lines
                    yield f"{counter}. {first}"
                    for line in rest:
                        if line:
                            yield f"   {line}"
                    counter += 1
                return
            if node_type == "listItem":
                for child in content:
                    yield from render(child)
                return
            if node_type == "codeBlock":
                language = current.get("attrs", {}).get("language")
                body_lines = [line for child in content for line in render(child)]
                body = "\n".join(body_lines)
                fence = "```"
                if language:
                    yield f"{fence}{language}"
                yield body
                yield fence
                return
            if node_type == "blockquote":
                for child in content:
                    child_lines = list(render(child))
                    for line in child_lines:
                        prefix = "> " if line else ">"
                        yield f"{prefix}{line}" if line else prefix.rstrip()
                return
            if node_type == "rule":
                yield "---"
                return
            if node_type == "panel":
                for child in content:
                    yield from render(child)
                return
            if node_type == "hardBreak":
                yield ""
                return
            # Fallback: render nested content without additional formatting.
            for child in content:
                yield from render(child)
            return
        if isinstance(current, list):
            for child in current:
                yield from render(child)
            return
        if isinstance(current, str):
            yield current
            return
        return

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

    raw_lines = list(render(node))
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


def _normalize_text_value(
    value: Any, *, allow_atlassian_document: bool = False
) -> str | None:
    """Coerce provider payload fields into Markdown text."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip("\n")
        return text.strip() or None
    if (
        allow_atlassian_document
        and isinstance(value, dict)
        and value.get("type") == "doc"
    ):
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
            _normalize_text_value(
                item, allow_atlassian_document=allow_atlassian_document
            )
            for item in value
        ]
        joined = "\n".join(part for part in parts if part)
        if not joined:
            return None
        stripped = joined.strip()
        return stripped or None
    return None


def _search_nested_text(
    source: Any, *, keywords: tuple[str, ...] = ("description", "body")
) -> str | None:
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


def _extract_issue_description(
    issue: ExternalIssue, provider: str | None
) -> str | None:
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
        fields = (
            payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        )
        description = _normalize_text_value(
            fields.get("description"), allow_atlassian_document=True
        )
        if description:
            return description
        rendered_fields = (
            payload.get("renderedFields")
            if isinstance(payload.get("renderedFields"), dict)
            else {}
        )
        rendered_description = _normalize_text_value(rendered_fields.get("description"))
        if rendered_description:
            return rendered_description
        return _search_nested_text(payload)

    for key in ("description", "body", "content", "details"):
        text = _normalize_text_value(payload.get(key))
        if text:
            return text

    return _search_nested_text(payload)


def _format_issue_comments(comments: list[dict[str, Any]]) -> str:
    """Format issue comments into Markdown for inclusion in agent context.

    Args:
        comments: List of comment dictionaries with keys: author, body, created_at, url

    Returns:
        Formatted markdown string with all comments, or empty string if no comments
    """
    if not comments:
        return ""

    formatted_comments: list[str] = []
    for comment in comments:
        author = comment.get("author") or "Unknown"
        body = comment.get("body", "").strip()
        created_at = comment.get("created_at")
        url = comment.get("url")

        if not body:
            continue

        # Format timestamp if available
        timestamp = ""
        if created_at:
            if isinstance(created_at, str):
                timestamp = created_at
            else:
                timestamp = format_issue_datetime(created_at)

        # Build comment header
        header = f"**{author}**"
        if timestamp:
            header += f" on {timestamp}"
        if url:
            header += f" ([link]({url}))"

        # Format comment body with indentation
        formatted_body = body.strip()

        # Combine header and body
        formatted_comments.append(f"{header}\n\n{formatted_body}")

    if not formatted_comments:
        return ""

    return "\n\n---\n\n".join(formatted_comments)


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
    other_issues = [issue for issue in all_issues if issue.id != primary_issue.id]
    issue_description = _extract_issue_description(primary_issue, provider)

    other_issues_section = (
        "\n".join(
            f"- {summarize_issue(issue, include_url=True)}" for issue in other_issues
        )
        or "None listed."
    )

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

    # Format issue comments
    comments = primary_issue.comments or []
    comments_section = _format_issue_comments(comments)
    comments_block = ""
    if comments_section:
        comment_count = len([c for c in comments if c.get("body", "").strip()])
        comments_block = dedent(
            f"""
            ## Issue Comments ({comment_count})

            {comments_section}
            """
        ).strip()

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
    # Add comments section after Issue Description if available
    if comments_block:
        # Insert comments section after Issue Description
        issue_desc_marker = "## Issue Description"
        project_context_marker = "## Project Context"
        if issue_desc_marker in content and project_context_marker in content:
            parts = content.split(project_context_marker, 1)
            content = (
                f"{parts[0]}\n\n{comments_block}\n\n{project_context_marker}{parts[1]}"
            )
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


def extract_issue_description_html(issue: ExternalIssue) -> str | None:
    """Extract pre-rendered HTML description from Jira's renderedFields.

    For Jira issues, the API returns pre-rendered HTML in renderedFields.description
    when expand=["renderedFields"] is used. This HTML is already formatted by Jira
    and is preferable to re-rendering wiki markup or ADF ourselves.

    Args:
        issue: The ExternalIssue to extract description from

    Returns:
        Pre-rendered HTML string if available, None otherwise
    """
    payload = issue.raw_payload or {}
    if not payload:
        return None

    integration = (
        issue.project_integration.integration if issue.project_integration else None
    )
    provider = (integration.provider if integration else "").lower()

    # Only Jira has renderedFields with pre-rendered HTML
    if provider != "jira":
        return None

    rendered_fields = payload.get("renderedFields")
    if not isinstance(rendered_fields, dict):
        return None

    description_html = rendered_fields.get("description")
    if not description_html or not isinstance(description_html, str):
        return None

    return description_html.strip() or None


def write_local_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
    filename: str = DEFAULT_CONTEXT_FILENAME,
    *,
    identity_user: User | None = None,
) -> tuple[Path, list[str]]:
    """Alias for tracked issue context writing (kept for compatibility).

    Returns:
        tuple[Path, list[str]]: Path to the written file and list of sources that were merged
    """
    return write_tracked_issue_context(
        project,
        primary_issue,
        all_issues,
        filename=filename,
        identity_user=identity_user,
    )


def write_ai_assisted_issue_context(
    project: Project,
    issue: ExternalIssue,
    user_description: str,
    issue_type_hint: str | None = None,
    create_branch: bool = False,
    filename: str = DEFAULT_TRACKED_CONTEXT_FILENAME,
    *,
    identity_user: User | None = None,
) -> tuple[Path, list[str]]:
    """Write AGENTS.override.md with instructions for AI to format a draft issue.

    This is used for AI-assisted issue creation where the AI needs to:
    1. Review the user's description
    2. Format it into a proper issue with title, description sections, labels
    3. Update the issue using aiops CLI
    4. Optionally create a feature/fix branch

    Returns:
        tuple[Path, list[str]]: Path to the written file and list of sources that were merged
    """
    linux_username: str | None = None
    if identity_user is not None:
        workspace_path = get_workspace_path(project, identity_user)
        if workspace_path is None:
            raise RuntimeError(
                f"Cannot determine workspace path for user {identity_user.email}"
            )
        repo_path = workspace_path
        linux_username = resolve_linux_username(identity_user)
        if not linux_username:
            raise RuntimeError(
                f"Cannot determine Linux username for user {identity_user.email}"
            )
        if not test_path(linux_username, str(repo_path)):
            raise RuntimeError(
                f"Workspace not initialized at {repo_path}. "
                "Please initialize the workspace first."
            )
    else:
        repo_path = Path(project.local_path)
        if not repo_path.exists():
            repo_path.mkdir(parents=True, exist_ok=True)

    context_path = repo_path / filename

    # Track which sources were merged
    sources_merged: list[str] = []

    # Load global context
    base_content = _load_base_instructions(repo_path, linux_username=linux_username)
    if base_content:
        # Check if we loaded from database or file
        try:
            from ..models import GlobalAgentContext
            global_context = GlobalAgentContext.query.first()
            if global_context and global_context.content and global_context.content.strip():
                sources_merged.append("global context")
        except RuntimeError:
            # Running outside of application context (e.g., in tests)
            pass

        # Check if AGENTS.md file exists in repo
        agents_md_path = repo_path / "AGENTS.md"
        if agents_md_path.exists() or (linux_username and test_path(linux_username, str(agents_md_path))):
            sources_merged.append("AGENTS.md")

    # Build the AI instructions
    type_hint_text = f" This appears to be a **{issue_type_hint}**." if issue_type_hint else ""
    branch_instruction = ""
    if create_branch:
        branch_instruction = dedent("""
            4. **Create a branch**: After updating the issue, create an appropriate feature or fix branch using:
               ```bash
               aiops git branch <project> <branch-name>
               aiops git checkout <project> <branch-name>
               ```
               Branch naming: `feature/<issue-id>-<slug>` or `fix/<issue-id>-<slug>`
        """).strip()

    issue_context = dedent(f"""
        # AI-Assisted Issue Creation

        ## Your Task

        You are helping to create a well-structured issue from a user's natural language description.{type_hint_text}

        **Draft Issue**: #{issue.external_id} - {issue.title}
        **Issue URL**: {issue.url}

        **User's Description**:
        ```
        {user_description}
        ```

        ## What You Need To Do

        1. **Review the description** and understand what the user wants to work on

        2. **Update the issue** with a proper structure using `aiops issues update`:
           - Create a clear, concise title (under 80 characters, no "Draft:" prefix)
           - Format the description with proper markdown sections:
             - **Overview**: Brief summary of the feature/fix
             - **Requirements**: Bullet list of what needs to be done
             - **Acceptance Criteria**: Checklist of items that must be completed
             - **Technical Notes** (optional): Implementation details or considerations
           - Add appropriate labels (e.g., feature, bug, enhancement, documentation)
           - Remove the "draft" label once formatted

        3. **Verify the changes**: Use `aiops issues get {issue.id}` to confirm the updates

        {branch_instruction}

        ## Example Commands

        ```bash
        # Update the issue title
        aiops issues update {issue.id} --title "Add user authentication with OAuth2"

        # Update the issue description (prepare markdown file first)
        cat > /tmp/issue-description.md <<'EOF'
        ## Overview
        Implement OAuth2 authentication allowing users to login with Google and GitHub.

        ## Requirements
        - OAuth2 integration with Google
        - OAuth2 integration with GitHub
        - Secure session storage
        - User profile management

        ## Acceptance Criteria
        - [ ] Users can login with Google account
        - [ ] Users can login with GitHub account
        - [ ] Sessions are encrypted and secure
        - [ ] User profiles sync from OAuth providers

        ## Technical Notes
        - Use industry-standard OAuth2 library
        - Store tokens encrypted in database
        - Implement CSRF protection
        EOF

        # Set the description from file
        aiops issues update {issue.id} --description "$(cat /tmp/issue-description.md)"

        # Add/remove labels
        aiops issues update {issue.id} --add-label feature --add-label security --remove-label draft
        ```

        ## Important Notes

        - Use the issue ID **{issue.id}** (database ID) not the external issue number
        - Make sure to remove the "draft" label when you're done
        - Be concise but thorough in the issue description
        - Focus on WHAT needs to be done, not HOW (that comes during implementation)
        - If the user's description is vague, make reasonable assumptions but note them

        Take your time to create a well-structured, professional issue. When you're done, summarize what you created.
    """).strip()

    appended_section = (
        f"{ISSUE_CONTEXT_SECTION_TITLE}\n"
        f"{ISSUE_CONTEXT_START}\n\n"
        f"{issue_context}\n\n"
        f"{ISSUE_CONTEXT_END}"
    )

    sections: list[str] = []
    if base_content:
        sections.append(base_content.rstrip())
    sections.append(appended_section.rstrip())

    # Add AI-assisted draft issue to sources
    sources_merged.append(f"AI-assisted draft issue #{issue.external_id}")

    final_content = "\n\n---\n\n".join(section for section in sections if section).rstrip() + "\n"

    # Write content (using sudo if needed)
    if identity_user is not None:
        try:
            cmd = [
                "sudo",
                "-n",
                "-u",
                linux_username,
                "tee",
                str(context_path),
            ]
            subprocess.run(
                cmd,
                input=final_content,
                capture_output=True,
                text=True,
                timeout=10.0,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Failed to write workspace file: {exc}") from exc
    else:
        context_path.write_text(final_content, encoding="utf-8")

    return context_path, sources_merged


def write_global_context_only(
    project: Project,
    filename: str = DEFAULT_TRACKED_CONTEXT_FILENAME,
    *,
    identity_user: User | None = None,
) -> tuple[Path, list[str]]:
    """Write AGENTS.override.md with only global context (no issue-specific content).

    This is used for generic sessions not tied to specific issues.

    Returns:
        tuple[Path, list[str]]: Path to the written file and list of sources that were merged
    """
    linux_username: str | None = None
    if identity_user is not None:
        workspace_path = get_workspace_path(project, identity_user)
        if workspace_path is None:
            raise RuntimeError(
                f"Cannot determine workspace path for user {identity_user.email}"
            )
        repo_path = workspace_path
        linux_username = resolve_linux_username(identity_user)
        if not linux_username:
            raise RuntimeError(
                f"Cannot determine Linux username for user {identity_user.email}"
            )
        if not test_path(linux_username, str(repo_path)):
            raise RuntimeError(
                f"Workspace not initialized at {repo_path}. "
                "Please initialize the workspace first."
            )
    else:
        repo_path = Path(project.local_path)
        if not repo_path.exists():
            repo_path.mkdir(parents=True, exist_ok=True)

    context_path = repo_path / filename

    # Track which sources were merged
    sources_merged: list[str] = []

    # Load global context
    base_content = _load_base_instructions(repo_path, linux_username=linux_username)
    if base_content:
        # Check if we loaded from database or file
        try:
            from ..models import GlobalAgentContext
            global_context = GlobalAgentContext.query.first()
            if global_context and global_context.content and global_context.content.strip():
                sources_merged.append("global context")
        except RuntimeError:
            # Running outside of application context (e.g., in tests)
            pass

        # Check if AGENTS.md file exists in repo
        agents_md_path = repo_path / "AGENTS.md"
        if agents_md_path.exists() or (linux_username and test_path(linux_username, str(agents_md_path))):
            sources_merged.append("AGENTS.md")

    # No issue context placeholder
    no_issue_message = "_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._"
    appended_section = (
        f"{ISSUE_CONTEXT_SECTION_TITLE}\n"
        f"{ISSUE_CONTEXT_START}\n\n"
        f"{no_issue_message}\n\n"
        f"{ISSUE_CONTEXT_END}"
    )

    sections: list[str] = []
    if base_content:
        sections.append(base_content.rstrip())
    sections.append(appended_section.rstrip())

    final_content = "\n\n---\n\n".join(section for section in sections if section).rstrip() + "\n"

    # Write content (using sudo if needed)
    if identity_user is not None:
        try:
            cmd = [
                "sudo",
                "-n",
                "-u",
                linux_username,
                "tee",
                str(context_path),
            ]
            subprocess.run(
                cmd,
                input=final_content,
                capture_output=True,
                text=True,
                timeout=10.0,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Failed to write workspace file: {exc}") from exc
    else:
        context_path.write_text(final_content, encoding="utf-8")

    return context_path, sources_merged


def write_tracked_issue_context(
    project: Project,
    primary_issue: ExternalIssue,
    all_issues: Iterable[ExternalIssue],
    filename: str = DEFAULT_TRACKED_CONTEXT_FILENAME,
    *,
    identity_user: User | None = None,
) -> tuple[Path, list[str]]:
    """Update a tracked AGENTS.override.md file with the latest context for the selected issue.

    Returns:
        tuple[Path, list[str]]: Path to the written file and list of sources that were merged
    """
    linux_username: str | None = None
    # Use user's workspace if identity_user is provided, otherwise use project.local_path
    if identity_user is not None:
        workspace_path = get_workspace_path(project, identity_user)
        if workspace_path is None:
            raise RuntimeError(
                f"Cannot determine workspace path for user {identity_user.email}"
            )
        repo_path = workspace_path
        linux_username = resolve_linux_username(identity_user)
        if not linux_username:
            raise RuntimeError(
                f"Cannot determine Linux username for user {identity_user.email}"
            )
        # For user workspaces, require that the workspace is already initialized
        if not test_path(linux_username, str(repo_path)):
            raise RuntimeError(
                f"Workspace not initialized at {repo_path}. "
                "Please initialize the workspace first."
            )
    else:
        repo_path = Path(project.local_path)
        if not repo_path.exists():
            repo_path.mkdir(parents=True, exist_ok=True)

    context_path = repo_path / filename

    # Track which sources were merged
    sources_merged: list[str] = []

    # Load base instructions, using sudo when linux_username is set
    base_content = _load_base_instructions(repo_path, linux_username=linux_username)
    if base_content:
        # Check if we loaded from database or file
        try:
            from ..models import GlobalAgentContext
            global_context = GlobalAgentContext.query.first()
            if global_context and global_context.content and global_context.content.strip():
                sources_merged.append("global context")
        except RuntimeError:
            # Running outside of application context (e.g., in tests)
            pass

        # Check if AGENTS.md file exists in repo
        agents_md_path = repo_path / "AGENTS.md"
        if agents_md_path.exists() or (linux_username and test_path(linux_username, str(agents_md_path))):
            sources_merged.append("AGENTS.md")

    issue_content = render_issue_context(
        project,
        primary_issue,
        all_issues,
        identity_user=identity_user,
    ).rstrip()
    sources_merged.append(f"issue #{primary_issue.external_id}")

    header_note = "NOTE: Generated issue context. Update before publishing if needed."
    appended_section = (
        f"{ISSUE_CONTEXT_SECTION_TITLE}\n"
        f"{ISSUE_CONTEXT_START}\n\n"
        f"{header_note}\n\n"
        f"{issue_content}\n"
        f"{ISSUE_CONTEXT_END}"
    )

    # Read existing content (using sudo if needed for user workspace)
    existing = ""
    if identity_user is not None:
        # User workspace - use sudo to read file
        try:
            sudo_result = run_as_user(
                linux_username,
                ["test", "-f", str(context_path)],
                check=False,
                timeout=5.0,
            )
            file_exists = sudo_result.success
            if file_exists:
                sudo_result = run_as_user(
                    linux_username,
                    ["cat", str(context_path)],
                    timeout=10.0,
                )
                existing = sudo_result.stdout
        except SudoError as exc:
            raise RuntimeError(f"Failed to read workspace file: {exc}") from exc
    else:
        # Legacy path - direct file access
        if context_path.exists():
            existing = context_path.read_text(encoding="utf-8")

    stripped_existing = existing.rstrip() if existing else ""

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
    final_content = updated.rstrip() + "\n"

    # Write content (using sudo if needed for user workspace)
    if identity_user is not None:
        # User workspace - use sudo to write file via tee
        try:
            cmd = [
                "sudo",
                "-n",
                "-u",
                linux_username,
                "tee",
                str(context_path),
            ]
            subprocess.run(
                cmd,
                input=final_content,
                capture_output=True,
                text=True,
                timeout=10.0,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Failed to write workspace file: {exc}") from exc
    else:
        # Legacy path - direct file write
        context_path.write_text(final_content, encoding="utf-8")

    return context_path, sources_merged


def _render_git_identity_section(identity_user: User | None) -> str:
    """Return a Markdown section describing the git identity to use."""
    if identity_user is None:
        return ""
    name: str = ""
    email: str = ""
    if identity_user and identity_user.name is not None:
        name = str(identity_user.name).strip()  # type: ignore  # type: ignore  # type: ignore
    if identity_user and identity_user.email is not None:
        email = str(identity_user.email).strip()  # type: ignore  # type: ignore  # type: ignore
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
        command_block = "```bash\n" + "\n".join(commands) + "\n```"

    section = dedent(
        f"""
        ## Git Identity
        Use this identity for commits created while working on this issue.

        {"\n".join(details)}

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
    if title_index != -1 and prefix[title_index:].strip().startswith(
        ISSUE_CONTEXT_SECTION_TITLE
    ):
        prefix = prefix[:title_index]

    cleaned_prefix = prefix.rstrip()
    cleaned_suffix = suffix.lstrip()
    if cleaned_prefix and cleaned_suffix:
        return f"{cleaned_prefix}\n\n{cleaned_suffix}"
    return cleaned_prefix or cleaned_suffix


def _load_base_instructions(
    repo_path: Path, *, linux_username: str | None = None
) -> str:
    """Load base instructions from database or AGENTS.md file.

    Priority order:
    1. Global agent context from database (if exists)
    2. AGENTS.md file from repository

    Args:
        repo_path: Path to repository root
        linux_username: If provided, use sudo to read file as this user

    Returns:
        Content of global agent context or AGENTS.md with issue context removed
    """
    # First, try to load from database
    try:
        from ..models import GlobalAgentContext

        global_context = GlobalAgentContext.query.order_by(
            GlobalAgentContext.updated_at.desc()
        ).first()
        if global_context and global_context.content:
            # Remove any issue context that might have been saved in the global content
            return _remove_existing_issue_context(global_context.content.rstrip())
    except Exception:
        # If database query fails (e.g., table doesn't exist yet), fall back to file
        pass

    # Fall back to reading AGENTS.md from repository
    base_path = repo_path / BASE_CONTEXT_FILENAME

    # Check if file exists and read it (using sudo if needed)
    if linux_username is not None:
        # User workspace - use sudo
        try:
            result = run_as_user(
                linux_username,
                ["test", "-f", str(base_path)],
                check=False,
                timeout=5.0,
            )
            if not result.success:
                return ""
            result = run_as_user(
                linux_username,
                ["cat", str(base_path)],
                timeout=10.0,
            )
            raw = result.stdout.rstrip()
        except SudoError:
            return ""
    else:
        # Legacy path - direct file access
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
        remainder = stripped_source[len(normalized_base) :].lstrip()
        if remainder.startswith("---"):
            remainder = remainder[3:].lstrip("- \n")
        return remainder.lstrip()

    return stripped_source
