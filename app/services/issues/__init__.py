from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from flask import current_app

from ...extensions import db
from ...models import ExternalIssue, ProjectIntegration, TenantIntegration


class IssueSyncError(Exception):
    """Raised when an external issue provider cannot be queried."""


@dataclass(slots=True)
class IssuePayload:
    external_id: str
    title: str
    status: Optional[str]
    assignee: Optional[str]
    url: Optional[str]
    labels: List[str]
    external_updated_at: Optional[datetime]
    raw: Dict[str, Any]


@dataclass(slots=True)
class IssueCreateRequest:
    summary: str
    description: Optional[str] = None
    issue_type: Optional[str] = None
    labels: Optional[List[str]] = None


ProviderFunc = Callable[[TenantIntegration, ProjectIntegration, Optional[datetime]], List[IssuePayload]]
CreateProviderFunc = Callable[[TenantIntegration, ProjectIntegration, IssueCreateRequest], IssuePayload]
CloseProviderFunc = Callable[[TenantIntegration, ProjectIntegration, str], IssuePayload]
AssignProviderFunc = Callable[[TenantIntegration, ProjectIntegration, str, List[str]], IssuePayload]

from . import github, gitlab, jira  # noqa: E402  (import depends on IssuePayload declaration)
from .utils import ProviderTestError, test_provider_credentials  # noqa: E402

PROVIDER_REGISTRY: Dict[str, ProviderFunc] = {
    "gitlab": gitlab.fetch_issues,
    "github": github.fetch_issues,
    "jira": jira.fetch_issues,
}

CREATE_PROVIDER_REGISTRY: Dict[str, CreateProviderFunc] = {
    "jira": jira.create_issue,
    "gitlab": gitlab.create_issue,
}

CLOSE_PROVIDER_REGISTRY: Dict[str, CloseProviderFunc] = {
    "github": github.close_issue,
    "gitlab": gitlab.close_issue,
    "jira": jira.close_issue,
}

ASSIGN_PROVIDER_REGISTRY: Dict[str, AssignProviderFunc] = {
    "github": github.assign_issue,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sync_project_integration(
    project_integration: ProjectIntegration,
    since: Optional[datetime] = None,
) -> List[ExternalIssue]:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError("Project integration is missing associated tenant integration.")

    provider_key = integration.provider.lower()
    fetcher = PROVIDER_REGISTRY.get(provider_key)
    if fetcher is None:
        raise IssueSyncError(f"Unsupported issue provider '{integration.provider}'.")

    effective_since = since or project_integration.last_synced_at
    try:
        payloads = fetcher(integration, project_integration, effective_since)
    except IssueSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Issue synchronization failed for project_integration=%s provider=%s",
            project_integration.id,
            provider_key,
        )
        raise IssueSyncError(str(exc)) from exc


def close_issue_for_project_integration(
    project_integration: ProjectIntegration,
    external_id: str,
) -> IssuePayload:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError("Project integration is missing associated tenant integration.")

    provider_key = integration.provider.lower()
    closer = CLOSE_PROVIDER_REGISTRY.get(provider_key)
    if closer is None:
        raise IssueSyncError(f"Issue closing is not supported for provider '{integration.provider}'.")

    try:
        return closer(integration, project_integration, external_id)
    except IssueSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Issue closing failed for project_integration=%s provider=%s issue=%s",
            project_integration.id,
            provider_key,
            external_id,
        )
        raise IssueSyncError(str(exc)) from exc

    existing_issues = {
        issue.external_id: issue
        for issue in ExternalIssue.query.filter_by(
            project_integration_id=project_integration.id
        ).all()
    }

    now = utcnow()
    updated_issues: List[ExternalIssue] = []
    for payload in payloads:
        issue = existing_issues.get(payload.external_id)
        if issue is None:
            issue = ExternalIssue(
                project_integration_id=project_integration.id,
                external_id=payload.external_id,
            )
            db.session.add(issue)
            existing_issues[payload.external_id] = issue

        issue.title = payload.title
        issue.status = payload.status
        issue.assignee = payload.assignee
        issue.url = payload.url
        issue.labels = payload.labels
        issue.external_updated_at = payload.external_updated_at
        issue.last_seen_at = now
        issue.raw_payload = payload.raw
        updated_issues.append(issue)

    project_integration.last_synced_at = now
    db.session.flush()
    return updated_issues


def sync_tenant_integrations(
    tenant_integrations: Iterable[ProjectIntegration],
) -> Dict[int, List[ExternalIssue]]:
    results: Dict[int, List[ExternalIssue]] = {}
    for p_integration in tenant_integrations:
        results[p_integration.id] = sync_project_integration(p_integration)
    db.session.commit()
    return results


def assign_issue_for_project_integration(
    project_integration: ProjectIntegration,
    external_id: str,
    assignees: List[str],
) -> IssuePayload:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError("Project integration is missing associated tenant integration.")

    provider_key = integration.provider.lower()
    assigner = ASSIGN_PROVIDER_REGISTRY.get(provider_key)
    if assigner is None:
        raise IssueSyncError(f"Issue assignment is not supported for provider '{integration.provider}'.")

    cleaned_assignees = [assignee.strip() for assignee in assignees if assignee and assignee.strip()]
    if not cleaned_assignees:
        raise IssueSyncError("At least one assignee is required.")

    try:
        return assigner(integration, project_integration, external_id, cleaned_assignees)
    except IssueSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Issue assignment failed for project_integration=%s provider=%s issue=%s",
            project_integration.id,
            provider_key,
            external_id,
        )
        raise IssueSyncError(str(exc)) from exc


def test_integration_connection(
    provider: str,
    api_token: str,
    base_url: Optional[str],
    username: Optional[str] = None,
) -> str:
    try:
        return test_provider_credentials(provider, api_token, base_url, username=username)
    except ProviderTestError as exc:
        raise IssueSyncError(str(exc)) from exc


# Prevent pytest from auto-collecting this helper as a test.
test_integration_connection.__test__ = False


def create_issue_for_project_integration(
    project_integration: ProjectIntegration,
    summary: str,
    description: Optional[str] = None,
    issue_type: Optional[str] = None,
    labels: Optional[List[str]] = None,
) -> IssuePayload:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError("Project integration is missing associated tenant integration.")

    provider_key = integration.provider.lower()
    creator = CREATE_PROVIDER_REGISTRY.get(provider_key)
    if creator is None:
        raise IssueSyncError(f"Issue creation is not supported for provider '{integration.provider}'.")

    request = IssueCreateRequest(
        summary=summary,
        description=description,
        issue_type=issue_type,
        labels=list(labels) if labels is not None else None,
    )

    try:
        return creator(integration, project_integration, request)
    except IssueSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Issue creation failed for project_integration=%s provider=%s",
            project_integration.id,
            provider_key,
        )
        raise IssueSyncError(str(exc)) from exc
