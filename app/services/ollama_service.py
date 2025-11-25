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

    Handles cases where JSON is wrapped in markdown code blocks or has extra text.

    Args:
        response_text: Raw response from Ollama model.

    Returns:
        Parsed JSON dictionary.

    Raises:
        OllamaServiceError: If JSON cannot be extracted or parsed.
    """
    logger.debug(f"Extracting JSON from response: type={type(response_text).__name__}, length={len(response_text)}")

    # Try to extract JSON from markdown code blocks first
    json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", response_text)
    if json_match:
        json_str = json_match.group(1)
        logger.debug("Found JSON in markdown code block")
    else:
        # Try to find raw JSON object - use non-greedy matching
        json_match = re.search(r"\{[\s\S]*?\}", response_text)
        if json_match:
            json_str = json_match.group(0)
            logger.debug(f"Found raw JSON, length={len(json_str)}")
        else:
            raise OllamaServiceError(
                f"No JSON found in response. First 200 chars: {response_text[:200]}"
            )

    logger.debug(f"JSON string to parse: length={len(json_str)}, first_50={repr(json_str[:50])}, last_50={repr(json_str[-50:])}")

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error(f"JSON parsing failed: {exc}")
        logger.error(f"JSON string: {json_str}")
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
        # The ollama client returns a GenerateResponse object, not a dict
        generated_text = ""
        if hasattr(response, 'response'):
            # GenerateResponse object has a 'response' attribute
            generated_text = response.response
        elif isinstance(response, dict):
            generated_text = response.get("response", "")
        else:
            generated_text = str(response)

        # Ensure it's a string
        if not isinstance(generated_text, str):
            generated_text = str(generated_text)

        if not generated_text or generated_text.strip() == "":
            raise OllamaServiceError("Ollama returned empty response")

        logger.info(
            "Ollama generation successful",
            extra={"response_length": len(generated_text)},
        )

        # Debug: Log the type and first chars of generated_text
        logger.info(
            f"Generated text before extraction: type={type(generated_text).__name__}, "
            f"length={len(generated_text)}, first_50={repr(generated_text[:50])}"
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
