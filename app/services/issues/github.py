from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from ...models import ProjectIntegration
from . import (
    IssueCommentPayload,
    IssueCreateRequest,
    IssuePayload,
    IssueSyncError,
)
from .utils import ensure_base_url

try:  # pragma: no cover - import guard for optional dependency
    from github.GithubException import GithubException as GithubAPIException
except Exception:  # pragma: no cover - fallback stub for type checking
    class GithubAPIException(Exception):  # type: ignore[no-redef]
        """Fallback GitHub exception stub when PyGithub is unavailable."""

        pass

MAX_COMMENTS_PER_ISSUE = 20


def _resolve_milestone_number(repo: Any, reference: str | None) -> int | None:
    if not reference:
        return None
    text = str(reference).strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return None

    try:
        milestones = repo.get_milestones(state="all")
    except GithubAPIException:
        return None
    except Exception:  # pragma: no cover - best effort matching
        return None

    target = text.lower()
    for milestone in milestones:
        title = getattr(milestone, "title", "") or ""
        if str(title).strip().lower() != target:
            continue
        number = getattr(milestone, "number", None)
        if number is None:
            continue
        try:
            return int(number)
        except (TypeError, ValueError):
            continue
    return None


def _format_github_error(exc: Any) -> str:
    """Format a GithubException into a readable error message."""
    status = getattr(exc, "status", "unknown")
    data = getattr(exc, "data", {}) if hasattr(exc, "data") else {}
    message = data.get("message") if isinstance(data, dict) else None

    # Build error message with all available context
    error_parts = [f"GitHub API error {status}"]
    if message:
        error_parts.append(message)
    elif data and str(data) != "{}":
        # If no message but we have data, show the full data
        error_parts.append(str(data))

    return " - ".join(error_parts)


def _build_client(integration: Any, base_url: str | None = None):
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
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    since: Optional[datetime] = None,
) -> List[IssuePayload]:
    repo_path = project_integration.external_identifier
    if not repo_path:
        raise IssueSyncError(
            "GitHub project integration requires an owner/repo identifier."
        )

    client = _build_client(integration)
    try:
        repo = client.get_repo(repo_path)
        # Build kwargs for get_issues - only include 'since' if provided
        issues_kwargs: dict[str, Any] = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
        }
        if since:
            since_value = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
            issues_kwargs["since"] = since_value
        issues = repo.get_issues(**issues_kwargs)
    except GithubAPIException as exc:
        raise IssueSyncError(_format_github_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc

    payloads: List[IssuePayload] = []
    for issue in issues:
        if issue.pull_request is not None:
            continue
        payloads.append(_issue_to_payload(issue))
    return payloads


def create_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    request: IssueCreateRequest,
    *,
    assignee: str | None = None,
    creator_user_id: int | None = None,
    creator_username: str | None = None,
) -> IssuePayload:
    repo_path = project_integration.external_identifier
    if not repo_path:
        raise IssueSyncError(
            "GitHub project integration requires an owner/repo identifier."
        )

    summary = (request.summary or "").strip()
    if not summary:
        raise IssueSyncError("Issue summary is required.")

    client = _build_client(integration)
    try:
        from github.GithubObject import NotSet

        repo = client.get_repo(repo_path)
        milestone_value = _resolve_milestone_number(repo, request.milestone)

        # PyGithub's create_issue uses NotSet for optional parameters
        # Passing None will fail assertions, so we must use NotSet for omitted values
        body = request.description if request.description else NotSet
        labels = request.labels if request.labels else NotSet
        assignees = [assignee] if assignee else NotSet
        milestone = milestone_value if milestone_value is not None else NotSet

        issue = repo.create_issue(
            title=summary,
            body=body,
            labels=labels,
            milestone=milestone,
            assignees=assignees,
        )

        # Add attribution comment if creator information is provided
        # This helps track who actually requested the issue creation when using shared credentials
        if creator_username:
            try:
                attribution = f"_Created via aiops by @{creator_username}_"
                issue.create_comment(attribution)
            except Exception as exc:  # noqa: BLE001
                # Don't fail the whole operation if commenting fails
                from flask import current_app
                current_app.logger.warning(
                    f"Failed to add attribution comment to issue #{issue.number}: {exc}"
                )
    except GithubAPIException as exc:
        raise IssueSyncError(_format_github_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc

    return _issue_to_payload(issue)


def close_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    external_id: str,
) -> IssuePayload:
    repo_path = project_integration.external_identifier
    if not repo_path:
        raise IssueSyncError(
            "GitHub project integration requires an owner/repo identifier."
        )

    try:
        issue_number = int(str(external_id).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise IssueSyncError("GitHub issue identifier must be a number.")

    client = _build_client(integration)
    try:
        repo = client.get_repo(repo_path)
        issue = repo.get_issue(number=issue_number)
        issue.edit(state="closed")
        issue = repo.get_issue(number=issue_number)
    except GithubAPIException as exc:
        raise IssueSyncError(_format_github_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc

    return _issue_to_payload(issue)


def assign_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    external_id: str,
    assignees: List[str],
) -> IssuePayload:
    repo_path = project_integration.external_identifier
    if not repo_path:
        raise IssueSyncError(
            "GitHub project integration requires an owner/repo identifier."
        )

    try:
        issue_number = int(str(external_id).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise IssueSyncError("GitHub issue identifier must be a number.")

    client = _build_client(integration)
    try:
        repo = client.get_repo(repo_path)
        issue = repo.get_issue(number=issue_number)
        issue.edit(assignees=assignees)
        issue = repo.get_issue(number=issue_number)
    except GithubAPIException as exc:
        raise IssueSyncError(_format_github_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc

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

    comments = _collect_issue_comments(issue)

    return IssuePayload(
        external_id=str(number),
        title=issue.title or "",
        status=issue.state,
        assignee=_resolve_assignee(issue),
        url=issue.html_url,
        labels=labels,
        external_updated_at=updated_at,
        raw=getattr(issue, "raw_data", {}) or {},
        comments=comments,
    )


def _resolve_assignee(issue: Any) -> Optional[str]:
    from .utils import normalize_assignee_name

    assignee = getattr(issue, "assignee", None)
    if assignee is None:
        return None
    # Prefer name over login for better consistency with other providers
    name = getattr(assignee, "name", None) or getattr(assignee, "login", None)
    return normalize_assignee_name(str(name) if name else None)


def _collect_issue_comments(issue: Any) -> List[IssueCommentPayload]:
    comments: List[IssueCommentPayload] = []
    try:
        paginated = issue.get_comments()
    except GithubAPIException:
        return comments

    for comment in paginated:
        author = None
        user = getattr(comment, "user", None)
        if user is not None:
            author = getattr(user, "login", None) or getattr(user, "name", None)
        created_at = getattr(comment, "created_at", None)
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        comment_id = getattr(comment, "id", None)
        comments.append(
            IssueCommentPayload(
                author=str(author) if author else None,
                body=getattr(comment, "body", "") or "",
                created_at=created_at,
                url=getattr(comment, "html_url", None),
                id=str(comment_id) if comment_id else None,
            )
        )
        if len(comments) > MAX_COMMENTS_PER_ISSUE:
            comments.pop(0)

    comments.reverse()
    return comments
