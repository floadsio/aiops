from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

from ...models import TenantIntegration

DEFAULT_TIMEOUT = 15.0


class ProviderTestError(Exception):
    """Raised when provider credentials cannot be verified."""


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_timeout(integration: TenantIntegration) -> float:
    settings = integration.settings or {}
    timeout_value = settings.get("timeout_seconds")
    if timeout_value is None:
        return DEFAULT_TIMEOUT
    try:
        return float(timeout_value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def normalize_base_url(base_url: Optional[str], default: str) -> str:
    value = base_url or default
    return value.rstrip("/")


def ensure_base_url(integration: TenantIntegration, default: str) -> str:
    return normalize_base_url(integration.base_url, default)


def normalize_issue_status(status: Optional[str]) -> Tuple[str, str]:
    if not status:
        return "__none__", "No status"
    raw = status.strip()
    if not raw:
        return "__none__", "No status"
    lowered = raw.lower()
    normalized = {
        "opened": "open",
    }.get(lowered, lowered)
    label_overrides = {
        "__none__": "No status",
        "open": "Open",
        "closed": "Closed",
    }
    label = label_overrides.get(normalized) or raw
    return normalized, label


def test_provider_credentials(
    provider: str,
    api_token: str,
    base_url: Optional[str],
    username: Optional[str] = None,
) -> str:
    provider_key = (provider or "").lower()
    auth: Optional[HTTPBasicAuth] = None

    if provider_key == "gitlab":
        try:
            from gitlab import Gitlab
            from gitlab import exceptions as gitlab_exc
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise ProviderTestError("python-gitlab is required for GitLab integrations.") from exc

        endpoint_base = normalize_base_url(base_url, "https://gitlab.com")
        try:
            client = Gitlab(endpoint_base, private_token=api_token, timeout=DEFAULT_TIMEOUT)
            client.auth()
        except (gitlab_exc.GitlabAuthenticationError, gitlab_exc.GitlabGetError) as exc:
            status = getattr(exc, "response_code", "unknown")
            raise ProviderTestError(f"GitLab token rejected (status {status}).") from exc
        except gitlab_exc.GitlabError as exc:
            raise ProviderTestError(f"Unable to reach GitLab API: {exc}") from exc
        return "GitLab credentials verified."
    elif provider_key == "github":
        try:
            from github import Github
            from github.GithubException import GithubException
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise ProviderTestError("PyGithub is required for GitHub integrations.") from exc

        endpoint_base = normalize_base_url(base_url, "https://api.github.com")
        try:
            client = Github(api_token, base_url=endpoint_base, timeout=DEFAULT_TIMEOUT)
            client.get_user().login
        except GithubException as exc:
            status = getattr(exc, "status", "unknown")
            raise ProviderTestError(f"GitHub token rejected (status {status}).") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderTestError(f"Unable to reach GitHub API: {exc}") from exc
        return "GitHub credentials verified."
    elif provider_key == "jira":
        if not base_url:
            raise ProviderTestError("Jira integrations require a base URL.")
        if not username:
            raise ProviderTestError("Jira integrations require an account email.")
        endpoint_base = normalize_base_url(base_url, base_url)
        url = f"{endpoint_base}/rest/api/3/myself"
        headers = {
            "Accept": "application/json",
        }
        auth = HTTPBasicAuth(username, api_token)

        try:
            response = requests.get(url, headers=headers, auth=auth, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise ProviderTestError(f"Jira token rejected (status {status}).") from exc
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise ProviderTestError(f"Unable to reach Jira API: {exc}") from exc
        return "Jira credentials verified."
    else:
        raise ProviderTestError(f"Unsupported issue provider '{provider}'.")
