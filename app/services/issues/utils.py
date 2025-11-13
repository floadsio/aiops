from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
from requests import HTTPError
from requests.auth import HTTPBasicAuth

from ...models import ExternalIssue, TenantIntegration

DEFAULT_TIMEOUT_SECONDS = 15.0

_github_module: Any | None = None
try:  # pragma: no cover - optional dependency
    import github as _github_module  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency
    pass


def _ensure_github_module_placeholder() -> None:
    """Populate missing attributes on partially stubbed github modules used in tests."""
    module = sys.modules.get("github")
    if module is None:
        return
    if not hasattr(module, "Github"):

        class _GithubPlaceholder:  # pragma: no cover - placeholder only
            pass

        setattr(module, "Github", _GithubPlaceholder)
    if not hasattr(module, "GithubException"):

        class _GithubExceptionPlaceholder(
            Exception
        ):  # pragma: no cover - placeholder only
            pass

        setattr(module, "GithubException", _GithubExceptionPlaceholder)


_ensure_github_module_placeholder()


class ProviderTestError(Exception):
    """Raised when validating third-party issue provider credentials fails."""


def ensure_base_url(integration: TenantIntegration, fallback: str) -> str:
    """Return a normalized base URL, preferring the integration-provided value."""
    candidate = (getattr(integration, "base_url", None) or "").strip()
    if not candidate:
        candidate = (fallback or "").strip()
    if not candidate:
        raise ValueError("Base URL is required for the issue provider.")
    return _normalize_base_url(candidate)


def get_timeout(
    integration: TenantIntegration, *, default: float = DEFAULT_TIMEOUT_SECONDS
) -> float:
    """Read a per-integration request timeout, falling back to a sane default."""
    settings = getattr(integration, "settings", None) or {}
    timeout_value = settings.get("timeout") or settings.get("request_timeout")
    if timeout_value is None:
        return default
    try:
        timeout = float(timeout_value)
    except (TypeError, ValueError):
        return default
    return timeout if timeout > 0 else default


def parse_datetime(value: Any) -> Optional[datetime]:
    """Coerce a provider timestamp into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        elif len(text) > 5 and text[-5] in "+-" and ":" not in text[-5:]:
            offset_digits = text[-4:]
            if offset_digits.isdigit():
                text = f"{text[:-5]}{text[-5:-2]}:{text[-2:]}"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_OPEN_STATUS_TOKENS = {
    "open",
    "opened",  # GitLab uses "opened" instead of "open"
    "todo",
    "doing",
    "backlog",
    "triage",
    "ready",
    "progress",
    "review",
    "active",
    "blocked",  # Consider blocked as still actionable
    "pending",
}
_OPEN_STATUS_PHRASES = {
    "in progress",
    "in review",
    "under review",
    "ready for work",
    "ready for review",
    "needs review",
    "awaiting review",
}
_CLOSED_STATUS_TOKENS = {
    "closed",
    "done",
    "resolved",
    "fixed",
    "complete",
    "completed",
    "finished",
    "merged",
    "shipped",
    "deployed",
    "released",
    "cancelled",
    "canceled",
    "rejected",
    "declined",
}
_CLOSED_STATUS_PHRASES = {
    "ready for release",
    "ready for deploy",
    "ready for deployment",
    "won't fix",
    "wont fix",
    "won't do",
    "won't merge",
    "no longer needed",
}


def normalize_issue_status(status: Optional[str]) -> tuple[str, str]:
    """Map a raw provider status to a filter key and display label."""
    if status is None:
        return "__none__", "Unspecified"
    raw = status.strip()
    if not raw:
        return "__none__", "Unspecified"

    normalized = raw.replace("_", " ").replace("-", " ").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    lower_normalized = normalized.lower()
    tokens = _split_status_tokens(lower_normalized)

    if lower_normalized in _OPEN_STATUS_PHRASES or any(
        token in _OPEN_STATUS_TOKENS for token in tokens
    ):
        return "open", "Open"
    if lower_normalized in _CLOSED_STATUS_PHRASES or any(
        token in _CLOSED_STATUS_TOKENS for token in tokens
    ):
        return "closed", "Closed"

    slug = _slugify_status(lower_normalized)
    label = _humanize_status_label(raw)
    return slug or "__none__", label or "Unspecified"


def test_provider_credentials(
    provider: str,
    api_token: str,
    base_url: Optional[str],
    *,
    username: Optional[str] = None,
) -> str:
    """Perform a lightweight credential verification against the given provider."""
    provider_key = (provider or "").strip().lower()
    if provider_key == "github":
        return _verify_github_credentials(api_token, base_url)
    if provider_key == "gitlab":
        return _verify_gitlab_credentials(api_token, base_url)
    if provider_key == "jira":
        return _verify_jira_credentials(api_token, base_url, username=username)
    raise ProviderTestError(f"Unsupported issue provider '{provider}'.")


def format_issue_datetime(value: datetime | None) -> str:
    """Format timestamps for human-readable displays."""
    if value is None:
        return "Unknown"
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def summarize_issue(issue: ExternalIssue, include_url: bool = False) -> str:
    """Build a compact summary string for listing issues."""
    integration = (
        issue.project_integration.integration if issue.project_integration else None
    )
    provider = integration.provider if integration else "unknown"
    parts = [f"[{provider}] {issue.external_id}: {issue.title}"]
    parts.append(f"status={issue.status or 'unspecified'}")
    if issue.assignee:
        parts.append(f"assignee={issue.assignee}")
    if issue.labels:
        parts.append(f"labels={', '.join(issue.labels)}")
    parts.append(
        f"updated={format_issue_datetime(issue.external_updated_at or issue.updated_at or issue.created_at)}"
    )
    if include_url and issue.url:
        parts.append(f"url={issue.url}")
    return "; ".join(parts)


def _normalize_base_url(url: str) -> str:
    value = url.strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    if not parsed.hostname:
        raise ValueError("Base URL must include a hostname.")
    netloc = parsed.netloc or parsed.hostname
    path = parsed.path.rstrip("/")
    if path == "/":
        path = ""
    normalized = parsed._replace(netloc=netloc, path=path, query="", fragment="")
    return urlunsplit(normalized)


def _split_status_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^\w]+", value) if token]


def _humanize_status_label(raw: str) -> str:
    cleaned = raw.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return "Unspecified"
    parts = cleaned.split()
    humanized = [part if part.isupper() else part.capitalize() for part in parts]
    return " ".join(humanized)


def _slugify_status(value: str) -> str:
    tokens = _split_status_tokens(value)
    if not tokens:
        return "__none__"
    return "_".join(token.lower() for token in tokens)


def _integration_proxy(
    base_url: Optional[str], settings: Optional[dict[str, Any]] = None
) -> SimpleNamespace:
    return SimpleNamespace(base_url=base_url, settings=settings or {})


def _verify_github_credentials(api_token: str, base_url: Optional[str]) -> str:
    try:
        from github import Github
        from github.GithubException import (
            GithubException,
        )
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ProviderTestError(
            "GitHub support requires PyGithub. Install dependencies with 'make sync'."
        ) from exc

    integration = _integration_proxy(base_url)
    try:
        endpoint = ensure_base_url(integration, "https://api.github.com")
    except ValueError as exc:
        raise ProviderTestError(str(exc)) from exc
    timeout = get_timeout(integration)
    try:
        client = Github(api_token, base_url=endpoint, timeout=timeout)
        user = client.get_user()
    except GithubException as exc:
        status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
        message = (
            getattr(exc, "data", {}).get("message") if hasattr(exc, "data") else None
        )
        details = f"{status}" if status is not None else str(exc)
        if message:
            details = f"{details}: {message}" if details else message
        raise ProviderTestError(f"GitHub API error: {details}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ProviderTestError(str(exc)) from exc

    login = getattr(user, "login", None) or getattr(user, "name", None) or "GitHub user"
    return f"GitHub credentials verified for {login}."


def _verify_gitlab_credentials(api_token: str, base_url: Optional[str]) -> str:
    try:
        from gitlab import Gitlab
        from gitlab import exceptions as gitlab_exc
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ProviderTestError(
            "GitLab support requires python-gitlab. Install dependencies with 'make sync'."
        ) from exc

    integration = _integration_proxy(base_url)
    try:
        endpoint = ensure_base_url(integration, "https://gitlab.com")
    except ValueError as exc:
        raise ProviderTestError(str(exc)) from exc
    timeout = get_timeout(integration)
    try:
        client = Gitlab(endpoint, private_token=api_token, timeout=timeout)
        client.auth()
    except gitlab_exc.GitlabError as exc:
        status = getattr(exc, "response_code", None)
        details = f"{status}" if status is not None else str(exc)
        raise ProviderTestError(f"GitLab API error: {details}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ProviderTestError(str(exc)) from exc

    return "GitLab credentials verified."


def _verify_jira_credentials(
    api_token: str,
    base_url: Optional[str],
    *,
    username: Optional[str],
) -> str:
    if not username:
        raise ProviderTestError("Jira integration requires an account email.")
    if not base_url or not base_url.strip():
        raise ProviderTestError("Jira integration requires a base URL.")
    integration = _integration_proxy(base_url)
    try:
        endpoint = ensure_base_url(integration, base_url)
    except ValueError as exc:
        raise ProviderTestError(str(exc)) from exc
    api_endpoint = f"{endpoint.rstrip('/')}/rest/api/3/myself"
    timeout = get_timeout(integration)
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(username, api_token)
    try:
        response = requests.get(
            api_endpoint, headers=headers, auth=auth, timeout=timeout
        )
        response.raise_for_status()
    except HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        details = f"{status}" if status is not None else str(exc)
        raise ProviderTestError(f"Jira API error: {details}") from exc
    except requests.RequestException as exc:
        raise ProviderTestError(str(exc)) from exc

    return "Jira credentials verified."
