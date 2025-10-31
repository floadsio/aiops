from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from ...models import ProjectIntegration, TenantIntegration
from . import IssueCreateRequest, IssuePayload, IssueSyncError
from .utils import ensure_base_url


def _build_client(integration: TenantIntegration, base_url: str | None = None):
    try:
        from github import Github
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise IssueSyncError("PyGithub is required for GitHub integrations.") from exc

    endpoint = ensure_base_url(integration, base_url or "https://api.github.com")
    try:
        return Github(integration.api_token, base_url=endpoint)
    except Exception as exc:  # noqa: BLE001
        raise IssueSyncError(f"Unable to configure GitHub client: {exc}") from exc


def fetch_issues(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    since: Optional[datetime] = None,
) -> List[IssuePayload]:
    repo_path = project_integration.external_identifier
    if not repo_path:
        raise IssueSyncError("GitHub project integration requires an owner/repo identifier.")

    client = _build_client(integration)
    try:
        from github.GithubException import GithubException

        repo = client.get_repo(repo_path)
        since_value = None
        if since:
            since_value = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        issues = repo.get_issues(state="all", sort="updated", direction="desc", since=since_value)
    except GithubException as exc:
        status = getattr(exc, "status", "unknown")
        raise IssueSyncError(f"GitHub API error: {status}") from exc
    except Exception as exc:  # noqa: BLE001
        raise IssueSyncError(str(exc)) from exc

    payloads: List[IssuePayload] = []
    for issue in issues:
        if issue.pull_request is not None:
            continue
        payloads.append(_issue_to_payload(issue))
    return payloads


def create_issue(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    request: IssueCreateRequest,
) -> IssuePayload:
    repo_path = project_integration.external_identifier
    if not repo_path:
        raise IssueSyncError("GitHub project integration requires an owner/repo identifier.")

    summary = (request.summary or "").strip()
    if not summary:
        raise IssueSyncError("Issue summary is required.")

    client = _build_client(integration)
    try:
        from github.GithubException import GithubException

        repo = client.get_repo(repo_path)
        labels = request.labels or None
        issue = repo.create_issue(
            title=summary,
            body=request.description or None,
            labels=labels,
        )
    except GithubException as exc:
        status = getattr(exc, "status", "unknown")
        raise IssueSyncError(f"GitHub API error: {status}") from exc
    except Exception as exc:  # noqa: BLE001
        raise IssueSyncError(str(exc)) from exc

    return _issue_to_payload(issue)


def _issue_to_payload(issue: Any) -> IssuePayload:
    number = getattr(issue, "number", None)
    if number is None:
        raise IssueSyncError("GitHub issue payload missing identifier.")

    labels_raw = getattr(issue, "labels", []) or []
    labels = []
    for label in labels_raw:
        if hasattr(label, "name"):
            labels.append(str(label.name))
        else:
            labels.append(str(label))
    updated_at = getattr(issue, "updated_at", None)
    if updated_at and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    return IssuePayload(
        external_id=str(number),
        title=issue.title or "",
        status=issue.state,
        assignee=_resolve_assignee(issue),
        url=issue.html_url,
        labels=labels,
        external_updated_at=updated_at,
        raw=getattr(issue, "raw_data", {}) or {},
    )


def _resolve_assignee(issue: Any) -> Optional[str]:
    assignee = getattr(issue, "assignee", None)
    if assignee is None:
        return None
    login = getattr(assignee, "login", None) or getattr(assignee, "name", None)
    return str(login) if login else None
