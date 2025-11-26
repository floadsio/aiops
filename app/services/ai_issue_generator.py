"""AI-assisted issue generation service.

This module provides functionality to generate well-structured GitHub/GitLab/Jira
issues from natural language descriptions using self-hosted Ollama.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.ollama_service import (
    OllamaServiceError,
    OllamaUnavailableError,
    generate_issue_with_ollama,
)


class AIIssueGenerationError(Exception):
    """Raised when AI issue generation fails."""


def generate_issue_from_description(
    description: str,
    ai_tool: str | None = None,
    issue_type: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Generate a structured issue from a natural language description using Ollama.

    Args:
        description: Natural language description of what the user wants to work on
        ai_tool: AI tool to use (ignored, only Ollama is used)
        issue_type: Optional hint about issue type (feature, bug, etc.)
        user_id: User ID for context (ignored, not needed for Ollama)

    Returns:
        Dictionary with:
            - title: Generated issue title
            - description: Formatted issue description with sections
            - labels: List of appropriate labels
            - branch_prefix: 'feature' or 'fix'

    Raises:
        AIIssueGenerationError: If AI generation fails
    """
    try:
        return generate_issue_with_ollama(description, issue_type)
    except OllamaUnavailableError as exc:
        raise AIIssueGenerationError(
            f"Ollama is not available. Please ensure Ollama is running at the configured URL. Error: {exc}"
        ) from exc
    except OllamaServiceError as exc:
        raise AIIssueGenerationError(f"Ollama generation failed: {exc}") from exc
    except Exception as exc:
        raise AIIssueGenerationError(f"Unexpected error during issue generation: {exc}") from exc


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
