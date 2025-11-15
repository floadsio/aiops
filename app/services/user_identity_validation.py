"""Validation functions for user identity mappings.

This module provides validation for GitHub usernames, GitLab usernames,
and Jira account IDs to ensure they exist before creating mappings.
"""

from __future__ import annotations

from typing import Optional

import requests  # type: ignore[import-untyped]
from requests.auth import HTTPBasicAuth  # type: ignore[import-untyped]


class IdentityValidationError(Exception):
    """Raised when identity validation fails."""


def validate_github_username(
    username: str,
    api_token: str,
    base_url: Optional[str] = None,
) -> bool:
    """Validate that a GitHub username exists.

    Args:
        username: The GitHub username to validate
        api_token: GitHub API token for authentication
        base_url: Optional GitHub API base URL (defaults to https://api.github.com)

    Returns:
        True if the username exists

    Raises:
        IdentityValidationError: If validation fails
    """
    try:
        from github import Github
        from github.GithubException import GithubException, UnknownObjectException
    except ImportError as exc:
        raise IdentityValidationError(
            "GitHub support requires PyGithub. Install dependencies with 'make sync'."
        ) from exc

    username = username.strip()
    if not username:
        raise IdentityValidationError("GitHub username cannot be empty.")

    endpoint = base_url or "https://api.github.com"
    try:
        client = Github(api_token, base_url=endpoint)
        user = client.get_user(username)
        # Access a property to trigger API call
        _ = user.login
        return True
    except UnknownObjectException as exc:
        raise IdentityValidationError(
            f"GitHub user '{username}' not found."
        ) from exc
    except GithubException as exc:
        status = getattr(exc, "status", "unknown")
        raise IdentityValidationError(
            f"GitHub API error: {status}"
        ) from exc
    except Exception as exc:
        raise IdentityValidationError(str(exc)) from exc


def validate_gitlab_username(
    username: str,
    api_token: str,
    base_url: Optional[str] = None,
) -> bool:
    """Validate that a GitLab username exists.

    Args:
        username: The GitLab username to validate
        api_token: GitLab API token for authentication
        base_url: Optional GitLab base URL (defaults to https://gitlab.com)

    Returns:
        True if the username exists

    Raises:
        IdentityValidationError: If validation fails
    """
    try:
        from gitlab import Gitlab
        from gitlab import exceptions as gitlab_exc
    except ImportError as exc:
        raise IdentityValidationError(
            "GitLab support requires python-gitlab. Install dependencies with 'make sync'."
        ) from exc

    username = username.strip()
    if not username:
        raise IdentityValidationError("GitLab username cannot be empty.")

    endpoint = base_url or "https://gitlab.com"
    try:
        client = Gitlab(endpoint, private_token=api_token)
        # Search for users by username
        users = client.users.list(username=username, get_all=False)
        if not users:
            raise IdentityValidationError(f"GitLab user '{username}' not found.")
        # Verify exact match (GitLab search is case-insensitive)
        for user in users:
            if hasattr(user, "username") and user.username == username:
                return True
        raise IdentityValidationError(
            f"GitLab user '{username}' not found (case-sensitive match failed)."
        )
    except gitlab_exc.GitlabError as exc:
        status = getattr(exc, "response_code", "unknown")
        raise IdentityValidationError(
            f"GitLab API error: {status}"
        ) from exc
    except IdentityValidationError:
        raise
    except Exception as exc:
        raise IdentityValidationError(str(exc)) from exc


def validate_jira_account_id(
    account_id: str,
    api_token: str,
    base_url: str,
    username: str,
) -> bool:
    """Validate that a Jira account ID exists.

    Args:
        account_id: The Jira account ID to validate
        api_token: Jira API token for authentication
        base_url: Jira instance base URL
        username: Jira account email for authentication

    Returns:
        True if the account ID exists

    Raises:
        IdentityValidationError: If validation fails
    """
    account_id = account_id.strip()
    if not account_id:
        raise IdentityValidationError("Jira account ID cannot be empty.")

    if not base_url or not base_url.strip():
        raise IdentityValidationError("Jira base URL is required for validation.")

    if not username or not username.strip():
        raise IdentityValidationError("Jira username is required for validation.")

    # Normalize base URL
    endpoint = base_url.rstrip("/")
    if "://" not in endpoint:
        endpoint = f"https://{endpoint}"

    # Jira REST API endpoint for fetching user by account ID
    api_endpoint = f"{endpoint}/rest/api/3/user"
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(username, api_token)
    params = {"accountId": account_id}

    try:
        response = requests.get(
            api_endpoint,
            headers=headers,
            auth=auth,
            params=params,
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
        # Verify account ID matches
        if data.get("accountId") == account_id:
            return True
        raise IdentityValidationError(
            f"Jira account ID '{account_id}' returned unexpected data."
        )
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", "unknown")
        if status == 404:
            raise IdentityValidationError(
                f"Jira account ID '{account_id}' not found."
            ) from exc
        raise IdentityValidationError(
            f"Jira API error: {status}"
        ) from exc
    except requests.RequestException as exc:
        raise IdentityValidationError(str(exc)) from exc
    except Exception as exc:
        raise IdentityValidationError(str(exc)) from exc
