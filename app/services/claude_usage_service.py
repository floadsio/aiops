from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import requests
from flask import current_app

from ..extensions import db
from ..models import User
from .claude_config_service import load_claude_api_key


class ClaudeUsageError(RuntimeError):
    """Raised when Claude usage data cannot be retrieved."""


def fetch_and_update_usage(user_id: int) -> dict[str, int | None]:
    """
    Fetch Claude API usage stats for a user and update their database record.

    Returns a dict with usage information:
    - input_tokens_limit
    - input_tokens_remaining
    - output_tokens_limit
    - output_tokens_remaining
    - requests_limit
    - requests_remaining
    """
    api_key = load_claude_api_key(user_id=user_id)
    if not api_key:
        raise ClaudeUsageError("No Claude API key configured for this user")

    # Make a minimal API call to get rate limit headers
    # We'll use the Messages API with a very short prompt
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-3-5-haiku-20241022",  # Use the cheapest model
        "max_tokens": 1,  # Minimal output
        "messages": [{"role": "user", "content": "Hi"}],
    }

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=10,
        )
    except requests.RequestException as exc:
        current_app.logger.warning(
            "Failed to fetch Claude usage for user %s: %s", user_id, exc
        )
        raise ClaudeUsageError(f"Failed to contact Claude API: {exc}") from exc

    if response.status_code not in (200, 429):
        raise ClaudeUsageError(
            f"Claude API returned status {response.status_code}: {response.text}"
        )

    # Extract rate limit headers
    usage_data = {
        "input_tokens_limit": _parse_header_int(
            response.headers.get("anthropic-ratelimit-input-tokens-limit")
        ),
        "input_tokens_remaining": _parse_header_int(
            response.headers.get("anthropic-ratelimit-input-tokens-remaining")
        ),
        "output_tokens_limit": _parse_header_int(
            response.headers.get("anthropic-ratelimit-output-tokens-limit")
        ),
        "output_tokens_remaining": _parse_header_int(
            response.headers.get("anthropic-ratelimit-output-tokens-remaining")
        ),
        "requests_limit": _parse_header_int(
            response.headers.get("anthropic-ratelimit-requests-limit")
        ),
        "requests_remaining": _parse_header_int(
            response.headers.get("anthropic-ratelimit-requests-remaining")
        ),
    }

    # Update user record
    user = User.query.get(user_id)
    if user:
        user.claude_input_tokens_limit = usage_data["input_tokens_limit"]
        user.claude_input_tokens_remaining = usage_data["input_tokens_remaining"]
        user.claude_output_tokens_limit = usage_data["output_tokens_limit"]
        user.claude_output_tokens_remaining = usage_data["output_tokens_remaining"]
        user.claude_requests_limit = usage_data["requests_limit"]
        user.claude_requests_remaining = usage_data["requests_remaining"]
        user.claude_usage_last_updated = datetime.now(timezone.utc)
        db.session.add(user)
        db.session.commit()

    return usage_data


def get_cached_usage(user_id: int) -> Optional[dict[str, int | datetime | None]]:
    """Get cached usage data from the database without making an API call."""
    user = User.query.get(user_id)
    if not user:
        return None

    return {
        "input_tokens_limit": user.claude_input_tokens_limit,
        "input_tokens_remaining": user.claude_input_tokens_remaining,
        "output_tokens_limit": user.claude_output_tokens_limit,
        "output_tokens_remaining": user.claude_output_tokens_remaining,
        "requests_limit": user.claude_requests_limit,
        "requests_remaining": user.claude_requests_remaining,
        "last_updated": user.claude_usage_last_updated,
    }


def _parse_header_int(value: str | None) -> int | None:
    """Parse an integer from a header value, returning None if invalid."""
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


__all__ = [
    "ClaudeUsageError",
    "fetch_and_update_usage",
    "get_cached_usage",
]
