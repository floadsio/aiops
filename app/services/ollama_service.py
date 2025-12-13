"""Ollama LLM service for AI-assisted issue generation.

This module provides a wrapper around the ollama-python library for generating
well-structured issue descriptions using self-hosted Ollama instances.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from flask import current_app

logger = logging.getLogger(__name__)


class OllamaServiceError(Exception):
    """Base exception for Ollama service errors."""


class OllamaUnavailableError(OllamaServiceError):
    """Raised when Ollama service is unavailable."""


@dataclass
class OllamaConfig:
    """Configuration for Ollama service."""

    api_url: str
    model: str
    timeout: float


def _get_ollama_config() -> OllamaConfig:
    """Extract Ollama configuration from Flask app config.

    Returns:
        OllamaConfig with API URL, model, and timeout settings.

    Raises:
        OllamaServiceError: If configuration is invalid.
    """
    api_url = current_app.config.get("OLLAMA_API_URL", "http://localhost:11434")
    model = current_app.config.get("OLLAMA_MODEL", "qwen2.5:7b")
    timeout = float(current_app.config.get("OLLAMA_TIMEOUT", 60.0))

    if not api_url or not model:
        raise OllamaServiceError("Ollama API URL and model must be configured")

    return OllamaConfig(api_url=api_url, model=model, timeout=timeout)


def _get_ollama_client() -> Any:
    """Get Ollama Python client with lazy imports.

    Returns:
        Ollama client instance.

    Raises:
        OllamaServiceError: If ollama library is not installed.
    """
    try:
        from ollama import Client
    except ImportError as exc:
        raise OllamaServiceError(
            "ollama-python library is not installed. "
            "Install it with: uv pip install ollama"
        ) from exc

    config = _get_ollama_config()
    try:
        client = Client(host=config.api_url)
        return client
    except Exception as exc:
        raise OllamaUnavailableError(
            f"Failed to connect to Ollama at {config.api_url}: {exc}"
        ) from exc


def _extract_json_from_response(response_text: str) -> dict[str, Any]:
    """Extract and parse JSON from response text.

    Handles cases where JSON is wrapped in markdown code blocks or has extra text,
    and fixes unescaped newlines in string fields.

    Args:
        response_text: Raw response from Ollama model.

    Returns:
        Parsed JSON dictionary.

    Raises:
        OllamaServiceError: If JSON cannot be extracted or parsed.
    """
    # Try to extract JSON from markdown code blocks first
    json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", response_text)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if json_match:
            json_str = json_match.group(0)
        else:
            raise OllamaServiceError(
                f"No JSON found in response. First 200 chars: {response_text[:200]}"
            )

    # Log initial state for debugging - use stderr to ensure it shows
    import sys
    debug_info = {
        "json_length": len(json_str),
        "first_100_chars_repr": repr(json_str[:100]),
        "first_100_chars": json_str[:100],
        "has_newline_after_brace": '{\n' in json_str or '{\r' in json_str,
        "char_code_after_brace": ord(json_str[1]) if len(json_str) > 1 else None,
    }
    print(f"DEBUG: Attempting to parse JSON: {debug_info}", file=sys.stderr)
    logger.info("Attempting to parse JSON from Ollama response", extra=debug_info)

    # CRITICAL FIX: Ollama returns JSON with literal backslash-n sequences (\\n as two chars)
    # not actual newline characters. We need to unescape these BEFORE parsing.
    # Check if the JSON has literal backslash-n (char code 92 = backslash, followed by n)
    if len(json_str) > 1 and json_str[1] == '\\':
        # This looks like escaped JSON - unescape it
        # The string repr shows {\\ but actual content is {\ so we need to interpret escape sequences
        try:
            # Try using unicode_escape codec to handle the escape sequences
            json_str = json_str.encode('utf-8').decode('unicode-escape')
            logger.info("Unescaped JSON from Ollama response", extra={"new_first_50": repr(json_str[:50])})
        except Exception as e:
            logger.warning(f"Failed to unescape JSON: {e}", extra={"original_first_50": repr(json_str[:50])})

    try:
        # First, try standard JSON parsing
        return json.loads(json_str)
    except json.JSONDecodeError as initial_error:
        # If standard parsing fails, try multiple fixes for Ollama output issues
        print(f"DEBUG: Initial parse failed: {initial_error}", file=sys.stderr)
        logger.debug(f"Initial JSON parse failed: {initial_error}, trying fixes...", extra={"json_length": len(json_str)})

        # Step 1: Remove actual newlines and various whitespace patterns after structural characters
        # Ollama outputs {\n "key": , {\n\t "key": , {  \n  "key": with various spacing combinations
        # Use regex to handle all whitespace variations
        fixed_json = re.sub(r'([\{\[,:])\s*\n\s*', r'\1 ', json_str)
        print(f"DEBUG: Step 1 result (first 50): {repr(fixed_json[:50])}", file=sys.stderr)

        try:
            result = json.loads(fixed_json)
            print("DEBUG: Step 1 SUCCESS", file=sys.stderr)
            return result
        except json.JSONDecodeError as e1:
            print(f"DEBUG: Step 1 failed: {e1}", file=sys.stderr)
            # Step 2: Also remove newlines before closing brackets
            fixed_json = re.sub(r'\s*\n\s*([\}\]])', r'\1', fixed_json)
            print(f"DEBUG: Step 2 result (first 50): {repr(fixed_json[:50])}", file=sys.stderr)

            try:
                result = json.loads(fixed_json)
                print("DEBUG: Step 2 SUCCESS", file=sys.stderr)
                return result
            except json.JSONDecodeError as e2:
                print(f"DEBUG: Step 2 failed: {e2}", file=sys.stderr)
                # Step 3: Remove ALL whitespace sequences (multiple spaces/tabs/newlines) and replace with single space
                # This handles cases where there are multiple newlines or mixed whitespace
                fixed_json = re.sub(r'\s+', ' ', fixed_json)
                print(f"DEBUG: Step 3 result (first 50): {repr(fixed_json[:50])}", file=sys.stderr)

                try:
                    result = json.loads(fixed_json)
                    print("DEBUG: Step 3 SUCCESS", file=sys.stderr)
                    return result
                except json.JSONDecodeError as e3:
                    print(f"DEBUG: Step 3 failed: {e3}", file=sys.stderr)
                    # Step 4: If still failing, fix unescaped actual newlines in string values
                    # The Ollama model may output literal newlines in JSON string fields

                    # Find all quoted strings and fix newlines within them
                    def fix_string(match):
                        s = match.group(0)
                        # Replace literal newlines and carriage returns with escaped versions
                        s = s.replace('\r\n', '\\n')  # Windows line endings
                        s = s.replace('\n', '\\n')    # Unix line endings
                        s = s.replace('\r', '\\n')    # Mac line endings
                        return s

                    # Fix newlines within quoted strings
                    fixed_json = re.sub(r'"(?:[^"\\]|\\.)*"', fix_string, fixed_json)

                    try:
                        return json.loads(fixed_json)
                    except json.JSONDecodeError as exc:
                        # Include detailed debug info in error message
                        debug_msg = (
                            f"\nDEBUG INFO:\n"
                            f"  Original length: {len(json_str)}\n"
                            f"  Original first 100 (repr): {repr(json_str[:100])}\n"
                            f"  Char after brace: {repr(json_str[1]) if len(json_str) > 1 else 'N/A'} (code: {ord(json_str[1]) if len(json_str) > 1 else 'N/A'})\n"
                            f"  Has newline after brace: {'{\n' in json_str or '{\r' in json_str}\n"
                            f"  Step 1 result (first 50): {repr(json_str.replace(chr(10), ' ').replace(chr(13), ' ')[:50])}\n"
                            f"  Error position: {exc.pos}\n"
                            f"  Error at char: {repr(json_str[exc.pos] if exc.pos < len(json_str) else 'EOF')}"
                        )
                        logger.error(
                            f"Failed to parse JSON after all fixes: {exc}{debug_msg}",
                            extra={
                                "original_length": len(json_str),
                                "original_start": json_str[:100],
                                "error_pos": exc.pos,
                            }
                        )
                        raise OllamaServiceError(
                            f"Failed to parse JSON from response: {exc}. "
                            f"Text was: {json_str[:200]}"
                        ) from exc


def generate_issue_with_ollama(
    description: str,
    issue_type: str | None = None,
) -> dict[str, Any]:
    """Generate a structured issue from a natural language description using Ollama.

    Args:
        description: Natural language description of what the user wants to work on.
        issue_type: Optional hint about issue type (feature, bug, etc.).

    Returns:
        Dictionary with:
            - title: Generated issue title
            - description: Formatted issue description with sections
            - labels: List of appropriate labels
            - branch_prefix: 'feature' or 'fix'

    Raises:
        OllamaServiceError: If issue generation fails.
        OllamaUnavailableError: If Ollama service is unavailable.
    """
    client = _get_ollama_client()
    config = _get_ollama_config()

    # Construct prompt for Ollama to generate issue
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
5. Respond with ONLY the JSON object, no other text or markdown"""

    try:
        logger.info(
            "Calling Ollama for issue generation",
            extra={
                "model": config.model,
                "api_url": config.api_url,
                "description_length": len(description),
            },
        )

        response = client.generate(
            model=config.model,
            prompt=prompt,
            stream=False,
        )

        # Extract generated text from response
        if isinstance(response, dict):
            generated_text = response.get("response", "")
        else:
            generated_text = str(response)

        if not generated_text or generated_text.strip() == "":
            raise OllamaServiceError("Ollama returned empty response")

        logger.info(
            "Ollama generation successful",
            extra={"response_length": len(generated_text)},
        )

        # Extract and parse JSON from response
        issue_data = _extract_json_from_response(generated_text)

        # Validate required fields
        required_fields = ["title", "description", "labels", "branch_prefix"]
        missing_fields = [f for f in required_fields if f not in issue_data]
        if missing_fields:
            raise OllamaServiceError(
                f"Response missing required fields: {missing_fields}. "
                f"Response was: {generated_text[:200]}"
            )

        # Validate branch_prefix
        if issue_data["branch_prefix"] not in ["feature", "fix"]:
            logger.warning(
                f"Invalid branch_prefix '{issue_data['branch_prefix']}', defaulting to 'feature'"
            )
            issue_data["branch_prefix"] = "feature"

        # Ensure labels is a list
        if isinstance(issue_data["labels"], str):
            issue_data["labels"] = [
                label.strip() for label in issue_data["labels"].split(",")
            ]

        return issue_data

    except OllamaServiceError:
        raise
    except Exception as exc:
        logger.error(
            f"Unexpected error during Ollama generation: {exc}",
            exc_info=True,
        )
        raise OllamaServiceError(f"Unexpected error during generation: {exc}") from exc


@dataclass
class SlackIssueContext:
    """Context for elaborating a Slack issue request."""

    brief_text: str
    requester_name: str
    requester_email: str | None
    channel_name: str
    channel_id: str
    timestamp: str
    thread_context: str | None  # Parent message text if in thread
    project_name: str
    project_description: str | None
    tenant_name: str
    integration_provider: str  # github/gitlab/jira
    recent_issue_titles: list[str]  # Last 5-10 issues
    common_labels: list[str]
    global_agent_context: str | None = None  # Global agent instructions
    project_agents_md: str | None = None  # Project-specific AGENTS.md content


def elaborate_issue_for_slack(context: SlackIssueContext) -> dict[str, Any]:
    """Elaborate a brief Slack issue request into a well-structured issue.

    Uses full context about the requester, project, and recent issues to generate
    an issue that matches the project's style and conventions.

    Args:
        context: SlackIssueContext with all available context

    Returns:
        Dictionary with:
            - title: Elaborated issue title
            - description: Full issue description with sections

    Raises:
        OllamaServiceError: If elaboration fails
        OllamaUnavailableError: If Ollama service is unavailable
    """
    client = _get_ollama_client()
    config = _get_ollama_config()

    # Build context section for the prompt
    recent_issues_text = ""
    if context.recent_issue_titles:
        recent_issues_text = "\n".join(f"- {title}" for title in context.recent_issue_titles[:10])
        recent_issues_text = f"\nRecent issues in this project:\n{recent_issues_text}\n"

    labels_text = ""
    if context.common_labels:
        labels_text = f"\nCommon labels used: {', '.join(context.common_labels)}\n"

    thread_text = ""
    if context.thread_context:
        thread_text = f"\nThread context (parent message): {context.thread_context}\n"

    # Include agent context if available (truncate to avoid overwhelming the model)
    agent_context_text = ""
    if context.global_agent_context:
        # Truncate to first 2000 chars to avoid overwhelming the model
        truncated = context.global_agent_context[:2000]
        if len(context.global_agent_context) > 2000:
            truncated += "\n... (truncated)"
        agent_context_text += f"\n--- Global Agent Guidelines ---\n{truncated}\n"

    if context.project_agents_md:
        # Truncate to first 2000 chars
        truncated = context.project_agents_md[:2000]
        if len(context.project_agents_md) > 2000:
            truncated += "\n... (truncated)"
        agent_context_text += f"\n--- Project AGENTS.md ---\n{truncated}\n"

    prompt = f"""You are creating an issue for the "{context.project_name}" project ({context.tenant_name} organization).

Context:
- Requested by: {context.requester_name}{f' ({context.requester_email})' if context.requester_email else ''}
- Requested at: {context.timestamp}
- Source: Slack channel #{context.channel_name}
- Integration: {context.integration_provider.title()}
{thread_text}{recent_issues_text}{labels_text}{agent_context_text}
User request: "{context.brief_text}"

Generate a well-structured issue. Respond ONLY with valid JSON (no markdown, no code blocks, just raw JSON):

{{
  "title": "Clear, concise issue title (under 80 characters)",
  "description": "Detailed description with:\\n\\n## Overview\\n[What needs to be done and why]\\n\\n## Details\\n[Additional context, steps to reproduce if bug, requirements if feature]\\n\\n## Acceptance Criteria\\n- [ ] Criterion 1\\n- [ ] Criterion 2"
}}

Rules:
1. Title must be clear and actionable (under 80 chars)
2. Match the style of recent issues if available
3. Include relevant context from the request
4. For bugs: include steps to reproduce if inferable
5. For features: include clear requirements
6. Always include acceptance criteria
7. Respond with ONLY the JSON object, no other text"""

    try:
        logger.info(
            "Calling Ollama for Slack issue elaboration",
            extra={
                "model": config.model,
                "brief_text_length": len(context.brief_text),
                "project": context.project_name,
            },
        )

        response = client.generate(
            model=config.model,
            prompt=prompt,
            stream=False,
        )

        # Extract generated text from response
        if isinstance(response, dict):
            generated_text = response.get("response", "")
        else:
            generated_text = str(response)

        if not generated_text or generated_text.strip() == "":
            raise OllamaServiceError("Ollama returned empty response")

        logger.info(
            "Ollama elaboration successful",
            extra={"response_length": len(generated_text)},
        )

        # Extract and parse JSON from response
        issue_data = _extract_json_from_response(generated_text)

        # Validate required fields
        if "title" not in issue_data or "description" not in issue_data:
            raise OllamaServiceError(
                f"Response missing title or description. Response was: {generated_text[:200]}"
            )

        return {
            "title": issue_data["title"],
            "description": issue_data["description"],
        }

    except OllamaServiceError:
        raise
    except Exception as exc:
        logger.error(
            f"Unexpected error during Slack issue elaboration: {exc}",
            exc_info=True,
        )
        raise OllamaServiceError(f"Unexpected error during elaboration: {exc}") from exc


def check_ollama_health() -> tuple[bool, str | None]:
    """Check if Ollama service is available and healthy.

    Returns:
        Tuple of (is_healthy, error_message):
            - (True, None) if Ollama is available
            - (False, error_message) if Ollama is unavailable

    This function never raises exceptions.
    """
    try:
        _get_ollama_config()
    except OllamaServiceError as exc:
        return False, f"Configuration error: {exc}"

    try:
        client = _get_ollama_client()
        # Try to list models as a health check
        models = client.list()
        if not models:
            return False, "No models available in Ollama"
        return True, None
    except OllamaUnavailableError as exc:
        return False, f"Ollama unavailable: {exc}"
    except OllamaServiceError as exc:
        return False, f"Ollama error: {exc}"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"
