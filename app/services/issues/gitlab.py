from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from ...models import ProjectIntegration, TenantIntegration
from . import IssueCreateRequest, IssuePayload, IssueSyncError
from .utils import ensure_base_url, get_timeout, parse_datetime


def _build_client(integration: TenantIntegration, base_url: str | None = None):
    try:
        from gitlab import Gitlab
        from gitlab import exceptions as gitlab_exc
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise IssueSyncError(
            "python-gitlab is required for GitLab integrations."
        ) from exc

    endpoint = ensure_base_url(integration, base_url or "https://gitlab.com")
    try:
        client = Gitlab(
            endpoint,
            private_token=integration.api_token,
            timeout=get_timeout(integration),
        )
        return client
    except gitlab_exc.GitlabError as exc:  # pragma: no cover - configuration failure
        raise IssueSyncError(f"Unable to configure GitLab client: {exc}") from exc


def fetch_issues(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    since: Optional[datetime] = None,
) -> List[IssuePayload]:
    project_ref = project_integration.external_identifier
    if not project_ref:
        raise IssueSyncError(
            "GitLab project integration requires an external project path."
        )

    client = _build_client(integration)
    try:
        from gitlab import exceptions as gitlab_exc

        project = client.projects.get(project_ref)
        list_kwargs: dict[str, Any] = {
            "order_by": "updated_at",
            "sort": "desc",
            "per_page": 100,
            "all": True,
        }
        if since:
            if since.tzinfo is None:
                since_value = since.replace(tzinfo=timezone.utc)
            else:
                since_value = since.astimezone(timezone.utc)
            list_kwargs["updated_after"] = since_value.isoformat()
        issues = project.issues.list(**list_kwargs)
    except (gitlab_exc.GitlabAuthenticationError, gitlab_exc.GitlabGetError) as exc:
        status = getattr(exc, "response_code", "unknown")
        raise IssueSyncError(f"GitLab API error: {status}") from exc
    except gitlab_exc.GitlabError as exc:
        raise IssueSyncError(str(exc)) from exc

    payloads: List[IssuePayload] = []
    for issue in issues:
        external_id = getattr(issue, "id", None)
        if not external_id:
            continue
        payloads.append(
            IssuePayload(
                external_id=str(external_id),
                title=getattr(issue, "title", "") or "",
                status=getattr(issue, "state", None),
                assignee=_resolve_assignee(issue),
                url=getattr(issue, "web_url", None),
                labels=[str(label) for label in getattr(issue, "labels", [])],
                external_updated_at=parse_datetime(getattr(issue, "updated_at", None)),
                raw=issue.attributes if hasattr(issue, "attributes") else {},
            )
        )
    return payloads


def create_issue(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    request: IssueCreateRequest,
) -> IssuePayload:
    project_ref = project_integration.external_identifier
    if not project_ref:
        raise IssueSyncError(
            "GitLab project integration requires an external project path."
        )

    summary = (request.summary or "").strip()
    if not summary:
        raise IssueSyncError("Issue summary is required.")

    client = _build_client(integration)
    try:
        from gitlab import exceptions as gitlab_exc

        project = client.projects.get(project_ref)
        payload: dict[str, Any] = {"title": summary}
        if request.description:
            payload["description"] = request.description
        if request.labels:
            payload["labels"] = request.labels
        issue = project.issues.create(payload)
    except (gitlab_exc.GitlabAuthenticationError, gitlab_exc.GitlabCreateError) as exc:
        status = getattr(exc, "response_code", "unknown")
        raise IssueSyncError(f"GitLab API error: {status}") from exc
    except gitlab_exc.GitlabError as exc:
        raise IssueSyncError(str(exc)) from exc

    external_id = getattr(issue, "id", None)
    if not external_id:
        raise IssueSyncError("GitLab did not return an issue ID.")

    return IssuePayload(
        external_id=str(external_id),
        title=getattr(issue, "title", "") or "",
        status=getattr(issue, "state", None),
        assignee=_resolve_assignee(issue),
        url=getattr(issue, "web_url", None),
        labels=[str(label) for label in getattr(issue, "labels", [])],
        external_updated_at=parse_datetime(getattr(issue, "updated_at", None)),
        raw=issue.attributes if hasattr(issue, "attributes") else {},
    )


def close_issue(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    external_id: str,
) -> IssuePayload:
    project_ref = project_integration.external_identifier
    if not project_ref:
        raise IssueSyncError(
            "GitLab project integration requires an external project path."
        )

    identifier = str(external_id).strip()
    try:
        issue_ref = int(identifier)
    except (TypeError, ValueError):
        issue_ref = identifier

    client = _build_client(integration)
    try:
        from gitlab import exceptions as gitlab_exc

        project = client.projects.get(project_ref)
        issue = project.issues.get(issue_ref)
        issue.state_event = "close"
        issue.save()
        issue = project.issues.get(issue_ref)
    except (gitlab_exc.GitlabAuthenticationError, gitlab_exc.GitlabGetError) as exc:
        status = getattr(exc, "response_code", "unknown")
        raise IssueSyncError(f"GitLab API error: {status}") from exc
    except gitlab_exc.GitlabError as exc:
        raise IssueSyncError(str(exc)) from exc

    external_id_value = getattr(issue, "id", None) or identifier
    return IssuePayload(
        external_id=str(external_id_value),
        title=getattr(issue, "title", "") or "",
        status=getattr(issue, "state", None),
        assignee=_resolve_assignee(issue),
        url=getattr(issue, "web_url", None),
        labels=[str(label) for label in getattr(issue, "labels", [])],
        external_updated_at=parse_datetime(getattr(issue, "updated_at", None)),
        raw=issue.attributes if hasattr(issue, "attributes") else {},
    )


def _resolve_assignee(issue_payload: Any) -> Optional[str]:
    assignee = getattr(issue_payload, "assignee", None)
    if isinstance(assignee, dict):
        name = assignee.get("name") or assignee.get("username")
        return str(name) if name else None
    if isinstance(assignee, list) and assignee:
        primary = assignee[0]
        if isinstance(primary, dict):
            name = primary.get("name") or primary.get("username")
            return str(name) if name else None
    return None
