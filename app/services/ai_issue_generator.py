"""AI-assisted issue generation service.

This module provides functionality to generate well-structured GitHub/GitLab/Jira
issues from natural language descriptions using AI tools like Claude.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from typing import Any

from flask import current_app


class AIIssueGenerationError(Exception):
    """Raised when AI issue generation fails."""


def generate_issue_from_description(
    description: str,
    ai_tool: str = "claude",
    issue_type: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Generate a structured issue from a natural language description.

    Args:
        description: Natural language description of what the user wants to work on
        ai_tool: AI tool to use for generation (claude, codex, gemini)
        issue_type: Optional hint about issue type (feature, bug, etc.)
        user_id: User ID for authentication (required for codex, gemini)

    Returns:
        Dictionary with:
            - title: Generated issue title
            - description: Formatted issue description with sections
            - labels: List of appropriate labels
            - branch_prefix: 'feature' or 'fix'

    Raises:
        AIIssueGenerationError: If AI generation fails
    """
    tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    if ai_tool not in tool_commands:
        raise AIIssueGenerationError(f"Unsupported AI tool: {ai_tool}")

    command = tool_commands[ai_tool]

    # Construct prompt for AI to generate issue
    type_hint = f"This is a {issue_type}. " if issue_type else ""
    prompt = f"""You are helping a developer create a well-structured GitHub issue.

{type_hint}The developer wants to work on: {description}

Please generate a properly formatted issue. Respond ONLY with valid JSON (no markdown, no code blocks, just raw JSON):

{{
  "title": "Clear, concise issue title (under 80 characters)",
  "description": "Detailed issue description with:\\n\\n## Overview\\n[Problem statement or feature description]\\n\\n## Requirements\\n- Requirement 1\\n- Requirement 2\\n\\n## Acceptance Criteria\\n- [ ] Criterion 1\\n- [ ] Criterion 2\\n\\n## Technical Notes\\n[Optional implementation notes]",
  "labels": ["appropriate", "labels"],
  "branch_prefix": "feature or fix"
}}

Rules:
1. Title must be clear and concise (under 80 chars)
2. Description must include Overview, Requirements, and Acceptance Criteria sections
3. Labels should be relevant (bug, feature, enhancement, documentation, etc.)
4. branch_prefix should be "feature" for new features, "fix" for bug fixes
5. Respond with ONLY the JSON object, no other text
"""

    try:
        # Parse command if it's a string with arguments
        if isinstance(command, str):
            command_parts = shlex.split(command)
        else:
            command_parts = [command]

        # Set up authentication environment for AI tools
        env = None
        if ai_tool == "codex":
            # Codex requires authentication setup
            if user_id is None:
                raise AIIssueGenerationError(
                    "User ID required for Codex authentication"
                )
            try:
                from .codex_config_service import ensure_codex_auth
                auth_path = ensure_codex_auth(user_id)
                env = {
                    **current_app.config.get("AI_TOOL_ENV", {}),
                    "CODEX_CONFIG_DIR": str(auth_path.parent),
                    "CODEX_AUTH_FILE": str(auth_path),
                }
            except Exception as exc:
                raise AIIssueGenerationError(
                    f"Failed to set up Codex authentication: {exc}"
                ) from exc
        elif ai_tool == "gemini":
            # Gemini requires authentication setup
            if user_id is None:
                raise AIIssueGenerationError(
                    "User ID required for Gemini authentication"
                )
            try:
                from .gemini_config_service import ensure_user_config
                ensure_user_config(user_id)
                # Gemini uses its own config discovery, no env needed
            except Exception as exc:
                raise AIIssueGenerationError(
                    f"Failed to set up Gemini authentication: {exc}"
                ) from exc

        # Run AI tool with prompt
        if ai_tool == "claude":
            # For Claude, we use the CLI directly
            result = subprocess.run(
                command_parts + [prompt],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=env,
            )
        elif ai_tool == "codex":
            # For Codex, force the non-interactive exec subcommand (CLI expects it)
            codex_command = list(command_parts)
            if not any(token in {"exec", "e"} for token in codex_command[1:]):
                codex_command.append("exec")

            result = subprocess.run(
                codex_command + [prompt],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=env,
            )
        elif ai_tool == "gemini":
            # For Gemini
            result = subprocess.run(
                command_parts + [prompt],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=env,
            )
        else:
            raise AIIssueGenerationError(f"Unsupported AI tool: {ai_tool}")

        if result.returncode != 0:
            stderr = result.stderr or ""
            raise AIIssueGenerationError(
                f"AI tool failed ({result.returncode}): {stderr.strip()}"
            )

        output = result.stdout.strip()
        if not output:
            raise AIIssueGenerationError("AI tool produced no output")

        # Try to extract JSON from the output
        # Sometimes AI tools wrap JSON in code blocks or add extra text
        json_match = re.search(r"\{[\s\S]*\}", output)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = output

        # Parse JSON response
        try:
            issue_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise AIIssueGenerationError(
                f"Failed to parse AI response as JSON: {e}. Output was: {output[:200]}"
            )

        # Validate required fields
        required_fields = ["title", "description", "labels", "branch_prefix"]
        missing_fields = [f for f in required_fields if f not in issue_data]
        if missing_fields:
            raise AIIssueGenerationError(
                f"AI response missing required fields: {missing_fields}"
            )

        # Validate branch_prefix
        if issue_data["branch_prefix"] not in ["feature", "fix"]:
            issue_data["branch_prefix"] = "feature"  # Default to feature

        # Ensure labels is a list
        if isinstance(issue_data["labels"], str):
            issue_data["labels"] = [
                label.strip() for label in issue_data["labels"].split(",")
            ]

        return issue_data

    except subprocess.TimeoutExpired:
        raise AIIssueGenerationError("AI tool timed out after 30 seconds")
    except Exception as e:
        if isinstance(e, AIIssueGenerationError):
            raise
        raise AIIssueGenerationError(f"Unexpected error during AI generation: {e}")


def slugify_title(title: str, max_length: int = 50) -> str:
    """Convert issue title to a slug for branch naming.

    Args:
        title: Issue title
        max_length: Maximum length of slug

    Returns:
        Slugified title suitable for branch names
    """
    # Convert to lowercase
    slug = title.lower()

    # Remove special characters, keep alphanumeric and spaces
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)

    # Replace spaces with hyphens
    slug = re.sub(r"\s+", "-", slug)

    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)

    # Remove leading/trailing hyphens
    slug = slug.strip("-")

    # Truncate to max length
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]

    return slug


def generate_branch_name(
    issue_external_id: str, title: str, branch_prefix: str = "feature"
) -> str:
    """Generate a branch name from issue details.

    Args:
        issue_external_id: External issue ID (e.g., "36" for GitHub #36)
        title: Issue title
        branch_prefix: 'feature' or 'fix'

    Returns:
        Branch name like 'feature/36-ai-assisted-issue-creation'
    """
    slug = slugify_title(title)
    return f"{branch_prefix}/{issue_external_id}-{slug}"
