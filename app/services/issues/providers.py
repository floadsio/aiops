from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...models import ProjectIntegration, TenantIntegration
from . import IssueCreateRequest, IssuePayload, IssueSyncError
from . import github as github_provider
from . import gitlab as gitlab_provider
from . import jira as jira_provider
from .utils import get_effective_integration, get_timeout


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _payload_to_dict(payload: IssuePayload) -> Dict[str, Any]:
    """Convert IssuePayload dataclass to a serializable dict."""
    return {
        "external_id": payload.external_id,
        "title": payload.title,
        "status": payload.status,
        "assignee": payload.assignee,
        "url": payload.url,
        "labels": list(payload.labels),
        "external_updated_at": _serialize_datetime(payload.external_updated_at),
        "raw": payload.raw,
        "comments": [
            {
                "author": comment.author,
                "body": comment.body,
                "created_at": _serialize_datetime(comment.created_at),
                "url": comment.url,
            }
            for comment in payload.comments
        ],
    }


class BaseIssueProvider:
    """Base wrapper to provide a consistent provider interface."""

    def __init__(self, integration: TenantIntegration):
        self.integration = integration

    # The API only instantiates provider-specific subclasses. The base class
    # exists to document the expected interface.


class GitHubIssueProvider(BaseIssueProvider):
    """Issue provider wrapper for GitHub integrations."""

    def create_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        title: str,
        description: str = "",
        labels: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        request = IssueCreateRequest(
            summary=title,
            description=description,
            labels=list(labels) if labels else None,
        )
        # Use effective integration with project-level and user-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration, user_id
        )
        payload = github_provider.create_issue(
            effective_integration,
            project_integration,
            request,
            assignee=assignee,
        )
        return _payload_to_dict(payload)

    def update_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        repo = self._get_repo(project_integration)
        number = self._parse_issue_number(issue_number)
        try:
            issue = repo.get_issue(number=number)
        except github_provider.GithubAPIException as exc:
            raise IssueSyncError(github_provider._format_github_error(exc)) from exc

        edit_kwargs: Dict[str, Any] = {}
        if title:
            edit_kwargs["title"] = title
        if description is not None:
            edit_kwargs["body"] = description
        if status:
            normalized = status.strip().lower()
            if normalized in {"closed", "close"}:
                edit_kwargs["state"] = "closed"
            elif normalized in {"open", "reopen", "re-open"}:
                edit_kwargs["state"] = "open"
        if labels is not None:
            edit_kwargs["labels"] = labels

        if edit_kwargs:
            try:
                issue.edit(**edit_kwargs)
                issue = repo.get_issue(number=number)
            except github_provider.GithubAPIException as exc:
                raise IssueSyncError(github_provider._format_github_error(exc)) from exc

        payload = github_provider._issue_to_payload(issue)
        return _payload_to_dict(payload)

    def close_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        payload = github_provider.close_issue(
            effective_integration, project_integration, issue_number
        )
        return _payload_to_dict(payload)

    def reopen_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
    ) -> Dict[str, Any]:
        repo = self._get_repo(project_integration)
        number = self._parse_issue_number(issue_number)
        try:
            issue = repo.get_issue(number=number)
            issue.edit(state="open")
            issue = repo.get_issue(number=number)
        except github_provider.GithubAPIException as exc:
            raise IssueSyncError(github_provider._format_github_error(exc)) from exc
        payload = github_provider._issue_to_payload(issue)
        return _payload_to_dict(payload)

    def add_comment(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        body: str,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level and user-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration, user_id
        )
        # Create a temporary GitHub client with the effective credentials
        import github as _github
        timeout = get_timeout(effective_integration)  # type: ignore[arg-type]
        base_url = effective_integration.base_url or "https://api.github.com"
        gh_client = _github.Github(effective_integration.api_token, base_url=base_url, timeout=int(timeout))

        repo = gh_client.get_repo(project_integration.external_identifier)
        number = self._parse_issue_number(issue_number)
        try:
            issue = repo.get_issue(number=number)
            comment = issue.create_comment(body)
        except github_provider.GithubAPIException as exc:
            raise IssueSyncError(github_provider._format_github_error(exc)) from exc

        user = getattr(comment, "user", None)
        author = None
        if user is not None:
            author = getattr(user, "login", None) or getattr(user, "name", None)
        created_at = getattr(comment, "created_at", None)

        return {
            "author": str(author) if author else None,
            "body": getattr(comment, "body", "") or "",
            "created_at": _serialize_datetime(created_at),
            "url": getattr(comment, "html_url", None),
        }

    def update_comment(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        comment_id: str,
        body: str,
    ) -> Dict[str, Any]:
        """Update an existing comment on a GitHub issue.

        Args:
            project_integration: Project integration
            issue_number: Issue number (e.g. '42')
            comment_id: Comment ID to update
            body: New comment text

        Returns:
            Updated comment metadata

        Raises:
            IssueSyncError: On API errors
        """
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        # Create a temporary GitHub client with the effective credentials
        import github as _github
        timeout = get_timeout(effective_integration)  # type: ignore[arg-type]
        base_url = effective_integration.base_url or "https://api.github.com"
        gh_client = _github.Github(effective_integration.api_token, base_url=base_url, timeout=int(timeout))

        repo = gh_client.get_repo(project_integration.external_identifier)
        try:
            # Get the comment by ID and update it
            comment = repo.get_comment(int(comment_id))
            comment.edit(body)
            # Refresh to get updated data
            comment = repo.get_comment(int(comment_id))
        except github_provider.GithubAPIException as exc:
            raise IssueSyncError(github_provider._format_github_error(exc)) from exc
        except ValueError as exc:
            raise IssueSyncError(f"Invalid comment ID: {comment_id}") from exc

        user = getattr(comment, "user", None)
        author = None
        if user is not None:
            author = getattr(user, "login", None) or getattr(user, "name", None)
        updated_at = getattr(comment, "updated_at", None)

        return {
            "id": str(comment.id),
            "author": str(author) if author else None,
            "body": getattr(comment, "body", "") or "",
            "created_at": _serialize_datetime(getattr(comment, "created_at", None)),
            "updated_at": _serialize_datetime(updated_at),
            "url": getattr(comment, "html_url", None),
        }

    def assign_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        assignee: str,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        payload = github_provider.assign_issue(
            effective_integration,
            project_integration,
            issue_number,
            [assignee],
        )
        return _payload_to_dict(payload)

    def _get_repo(self, project_integration: ProjectIntegration):
        repo_path = project_integration.external_identifier
        if not repo_path:
            raise IssueSyncError(
                "GitHub project integration requires an owner/repo identifier."
            )
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        client = github_provider._build_client(effective_integration)
        try:
            return client.get_repo(repo_path)
        except github_provider.GithubAPIException as exc:
            raise IssueSyncError(github_provider._format_github_error(exc)) from exc

    @staticmethod
    def _parse_issue_number(external_id: str) -> int:
        try:
            return int(str(external_id).strip().lstrip("#"))
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise IssueSyncError("GitHub issue identifier must be a number.") from exc


class GitLabIssueProvider(BaseIssueProvider):
    """Basic wrapper around the GitLab provider functions."""

    def create_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        title: str,
        description: str = "",
        labels: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        request = IssueCreateRequest(
            summary=title,
            description=description,
            labels=list(labels) if labels else None,
        )
        # Use effective integration with project-level and user-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration, user_id
        )
        payload = gitlab_provider.create_issue(
            effective_integration,
            project_integration,
            request,
            assignee=assignee,
        )
        return _payload_to_dict(payload)

    def update_issue(self, **_: Any) -> Dict[str, Any]:
        raise IssueSyncError("Updating GitLab issues via API is not supported yet.")

    def close_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        payload = gitlab_provider.close_issue(
            effective_integration, project_integration, issue_number
        )
        return _payload_to_dict(payload)

    def reopen_issue(self, **_: Any) -> Dict[str, Any]:
        raise IssueSyncError("Reopening GitLab issues via API is not supported yet.")

    def add_comment(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        body: str,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level and user-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration, user_id
        )
        payload = gitlab_provider.create_comment(
            effective_integration,
            project_integration,
            issue_number,
            body,
        )
        # Convert IssueCommentPayload to dict format expected by API
        return {
            "id": payload.id,
            "author": payload.author,
            "body": payload.body,
            "created_at": _serialize_datetime(payload.created_at),
            "url": payload.url,
        }

    def assign_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        assignee: str,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        payload = gitlab_provider.assign_issue(
            effective_integration,
            project_integration,
            issue_number,
            assignee,
        )
        return _payload_to_dict(payload)


class JiraIssueProvider(BaseIssueProvider):
    """Basic wrapper around the Jira provider functions."""

    def create_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        title: str,
        description: str = "",
        labels: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        request = IssueCreateRequest(
            summary=title,
            description=description,
            labels=list(labels) if labels else None,
        )
        # Use effective integration with project-level and user-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration, user_id
        )
        payload = jira_provider.create_issue(
            effective_integration,
            project_integration,
            request,
            assignee_account_id=assignee,
        )
        return _payload_to_dict(payload)

    def update_issue(self, **_: Any) -> Dict[str, Any]:
        raise IssueSyncError("Updating Jira issues via API is not supported yet.")

    def close_issue(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        payload = jira_provider.close_issue(
            effective_integration, project_integration, issue_number
        )
        return _payload_to_dict(payload)

    def reopen_issue(self, **_: Any) -> Dict[str, Any]:
        raise IssueSyncError("Reopening Jira issues via API is not supported yet.")

    def add_comment(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        body: str,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level and user-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration, user_id
        )
        payload = jira_provider.create_comment(
            effective_integration,
            project_integration,
            issue_number,
            body,
        )
        # Convert IssueCommentPayload to dict format expected by API
        return {
            "id": payload.id,
            "author": payload.author,
            "body": payload.body,
            "created_at": _serialize_datetime(payload.created_at),
            "url": payload.url,
        }

    def update_comment(
        self,
        *,
        project_integration: ProjectIntegration,
        issue_number: str,
        comment_id: str,
        body: str,
    ) -> Dict[str, Any]:
        # Use effective integration with project-level credential overrides
        effective_integration = get_effective_integration(
            self.integration, project_integration
        )
        payload = jira_provider.update_comment(
            effective_integration,
            project_integration,
            issue_number,
            comment_id,
            body,
        )
        # Convert IssueCommentPayload to dict format expected by API
        return {
            "id": payload.id,
            "author": payload.author,
            "body": payload.body,
            "created_at": _serialize_datetime(payload.created_at),
            "url": payload.url,
        }

    def assign_issue(self, **_: Any) -> Dict[str, Any]:
        raise IssueSyncError("Assigning Jira issues via API is not supported yet.")
