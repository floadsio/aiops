from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional

from flask import current_app

from ...extensions import db
from ...models import ExternalIssue, ProjectIntegration, TenantIntegration

if TYPE_CHECKING:
    from .utils import IntegrationLike as IntegrationLike  # noqa: F401


@dataclass(slots=True)
class IssueCommentPayload:
    author: Optional[str]
    body: str
    created_at: Optional[datetime]
    url: Optional[str]
    id: Optional[str] = None  # Comment ID from the provider (Jira, GitHub, GitLab)
    body_html: Optional[str] = None  # Pre-rendered HTML from API (Jira, GitHub)


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
    comments: List[IssueCommentPayload] = field(default_factory=list)


@dataclass(slots=True)
class IssueCreateRequest:
    summary: str
    description: Optional[str] = None
    issue_type: Optional[str] = None
    labels: Optional[List[str]] = None
    priority: Optional[str] = None
    milestone: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None


class IssueSyncError(Exception):
    """Raised when an external issue provider cannot be queried."""


class IssueUpdateError(Exception):
    """Raised when an issue update request cannot be applied."""


ProviderFunc = Callable[
    [TenantIntegration, ProjectIntegration, Optional[datetime]], List[IssuePayload]
]
CreateProviderFunc = Callable[
    [TenantIntegration, ProjectIntegration, IssueCreateRequest], IssuePayload
]
CloseProviderFunc = Callable[[TenantIntegration, ProjectIntegration, str], IssuePayload]
AssignProviderFunc = Callable[
    [TenantIntegration, ProjectIntegration, str, List[str]], IssuePayload
]

from . import (  # noqa: E402  (import depends on IssuePayload declaration)
    github,
    gitlab,
    jira,
)
from .utils import (  # noqa: E402
    ProviderTestError,
    get_effective_integration,
    test_provider_credentials,
)

PROVIDER_REGISTRY: Dict[str, ProviderFunc] = {
    "gitlab": gitlab.fetch_issues,
    "github": github.fetch_issues,
    "jira": jira.fetch_issues,
}

CREATE_PROVIDER_REGISTRY: Dict[str, CreateProviderFunc] = {
    "github": github.create_issue,
    "gitlab": gitlab.create_issue,
    "jira": jira.create_issue,
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


ISSUE_STATUS_MAX_LENGTH = ExternalIssue.status.property.columns[0].type.length
_UTC = timezone.utc


def serialize_issue_comments(
    comments: List[IssueCommentPayload],
) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for comment in comments:
        created_at = comment.created_at
        if created_at:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=_UTC)
            created_value = created_at.astimezone(_UTC).isoformat()
        else:
            created_value = None
        entry = {
            "id": comment.id,
            "author": comment.author,
            "body": comment.body,
            "url": comment.url,
            "created_at": created_value,
        }
        # Include body_html if available (Jira, GitHub provide pre-rendered HTML)
        if comment.body_html:
            entry["body_html"] = comment.body_html
        serialized.append(entry)
    return serialized


def update_issue_status(issue_id: int, status: Optional[str]) -> ExternalIssue:
    """Update the stored status for a synced issue."""
    issue: ExternalIssue | None = ExternalIssue.query.get(issue_id)  # type: ignore[assignment]
    if issue is None:
        raise IssueUpdateError("Issue not found.")

    cleaned = (status or "").strip()
    if len(cleaned) > ISSUE_STATUS_MAX_LENGTH:
        raise IssueUpdateError(
            f"Status must be {ISSUE_STATUS_MAX_LENGTH} characters or fewer."
        )

    issue.status = cleaned or None
    db.session.flush()
    return issue


def sync_project_integration(
    project_integration: ProjectIntegration,
    since: Optional[datetime] = None,
    *,
    force_full: bool = False,
) -> List[ExternalIssue]:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError(
            "Project integration is missing associated tenant integration."
        )

    provider_key = integration.provider.lower()
    fetcher = PROVIDER_REGISTRY.get(provider_key)
    if fetcher is None:
        raise IssueSyncError(f"Unsupported issue provider '{integration.provider}'.")

    if force_full:
        effective_since = since
    else:
        effective_since = since or project_integration.last_synced_at  # type: ignore[assignment]

    # Use effective integration with project-level credential overrides
    effective_integration = get_effective_integration(integration, project_integration)

    try:
        payloads = fetcher(effective_integration, project_integration, effective_since)  # type: ignore[arg-type]
    except IssueSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Issue synchronization failed for project_integration=%s provider=%s",
            project_integration.id,
            provider_key,
        )
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc

    existing_issues = {
        issue.external_id: issue
        for issue in ExternalIssue.query.filter_by(
            project_integration_id=project_integration.id
        ).all()
    }

    # Get the tenant ID to check for manually assigned issues across projects
    tenant_id = None
    if project_integration.project and project_integration.project.tenant:
        tenant_id = project_integration.project.tenant_id

    # Find issues that exist elsewhere in the tenant and are manually assigned
    # These should not be synced to this project to avoid duplicates
    manually_assigned_external_ids: set[str] = set()
    if tenant_id:
        manually_assigned_issues = (
            ExternalIssue.query
            .join(ProjectIntegration)
            .join(Project)
            .filter(
                Project.tenant_id == tenant_id,
                ExternalIssue.manually_assigned == True,  # noqa: E712
                ExternalIssue.project_integration_id != project_integration.id,
            )
            .all()
        )
        manually_assigned_external_ids = {i.external_id for i in manually_assigned_issues}

    now = utcnow()
    updated_issues: List[ExternalIssue] = []
    for payload in payloads:
        # Skip issues that have been manually assigned to another project
        if payload.external_id in manually_assigned_external_ids:
            current_app.logger.debug(
                "Skipping issue %s - manually assigned to another project",
                payload.external_id,
            )
            continue

        issue = existing_issues.get(payload.external_id)
        if issue is None:
            issue = ExternalIssue(
                project_integration_id=project_integration.id,
                external_id=payload.external_id,
            )
            db.session.add(issue)
            existing_issues[payload.external_id] = issue
        elif issue.manually_assigned:
            # Don't update issues that are manually assigned to this project
            # (they should stay here but we might still want to update their data)
            # For now, we DO update the data but preserve the assignment
            pass

        issue.title = payload.title
        issue.status = payload.status
        issue.assignee = payload.assignee
        issue.url = payload.url
        issue.labels = payload.labels
        issue.external_updated_at = payload.external_updated_at
        issue.last_seen_at = now
        issue.raw_payload = payload.raw
        issue.comments = serialize_issue_comments(payload.comments)
        updated_issues.append(issue)

    project_integration.last_synced_at = now  # type: ignore[assignment]
    db.session.flush()
    return updated_issues


def close_issue_for_project_integration(
    project_integration: ProjectIntegration,
    external_id: str,
) -> IssuePayload:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError(
            "Project integration is missing associated tenant integration."
        )

    provider_key = integration.provider.lower()
    closer = CLOSE_PROVIDER_REGISTRY.get(provider_key)
    if closer is None:
        raise IssueSyncError(
            f"Issue closing is not supported for provider '{integration.provider}'."
        )

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
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc


def sync_tenant_integrations(
    tenant_integrations: Iterable[ProjectIntegration],
    *,
    force_full: bool = False,
) -> Dict[int, List[ExternalIssue]]:
    """Sync issues from multiple project integrations.

    Gracefully handles failures from individual integrations - if one integration
    fails (e.g., GitLab instance is down), other integrations will still be synced.

    Args:
        tenant_integrations: Project integrations to sync
        force_full: Whether to force full sync ignoring last sync time

    Returns:
        Dict mapping project_integration_id to synced issues for successful syncs.
        Failed integrations are logged but not included in results.
    """
    results: Dict[int, List[ExternalIssue]] = {}
    failed_integrations: List[tuple[int, str, str]] = []

    for p_integration in tenant_integrations:
        integration_name = (
            p_integration.integration.name if p_integration.integration else "Unknown"
        )
        provider = (
            p_integration.integration.provider if p_integration.integration else "unknown"
        )

        try:
            synced_issues = sync_project_integration(
                p_integration,
                force_full=force_full,
            )
            results[p_integration.id] = synced_issues  # type: ignore[index]
            current_app.logger.info(
                "Successfully synced %d issues for integration '%s' (provider=%s, id=%d)",
                len(synced_issues),
                integration_name,
                provider,
                p_integration.id,
            )
        except IssueSyncError as exc:
            # Log the error and continue with other integrations
            error_msg = str(exc)
            current_app.logger.error(
                "Failed to sync integration '%s' (provider=%s, id=%d): %s",
                integration_name,
                provider,
                p_integration.id,
                error_msg,
            )
            failed_integrations.append((p_integration.id, integration_name, error_msg))
        except Exception as exc:  # noqa: BLE001
            # Catch unexpected errors and continue
            error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
            current_app.logger.exception(
                "Unexpected error syncing integration '%s' (provider=%s, id=%d)",
                integration_name,
                provider,
                p_integration.id,
            )
            failed_integrations.append((p_integration.id, integration_name, error_msg))

    # Commit all successful syncs
    if results:
        db.session.commit()
        current_app.logger.info(
            "Issue sync completed: %d integrations succeeded, %d failed",
            len(results),
            len(failed_integrations),
        )
    else:
        current_app.logger.warning(
            "Issue sync completed with no successful integrations (%d failed)",
            len(failed_integrations),
        )

    # If all integrations failed, this might indicate a wider issue, but we still
    # don't raise an exception - the caller should check the results dict
    return results


def assign_issue_for_project_integration(
    project_integration: ProjectIntegration,
    external_id: str,
    assignees: List[str],
) -> IssuePayload:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError(
            "Project integration is missing associated tenant integration."
        )

    provider_key = integration.provider.lower()
    assigner = ASSIGN_PROVIDER_REGISTRY.get(provider_key)
    if assigner is None:
        raise IssueSyncError(
            f"Issue assignment is not supported for provider '{integration.provider}'."
        )

    cleaned_assignees = [
        assignee.strip() for assignee in assignees if assignee and assignee.strip()
    ]
    if not cleaned_assignees:
        raise IssueSyncError("At least one assignee is required.")

    try:
        return assigner(
            integration, project_integration, external_id, cleaned_assignees
        )
    except IssueSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Issue assignment failed for project_integration=%s provider=%s issue=%s",
            project_integration.id,
            provider_key,
            external_id,
        )
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc


def test_integration_connection(
    provider: str,
    api_token: str,
    base_url: Optional[str],
    username: Optional[str] = None,
) -> str:
    try:
        return test_provider_credentials(
            provider, api_token, base_url, username=username
        )
    except ProviderTestError as exc:
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc


# Prevent pytest from auto-collecting this helper as a test.
test_integration_connection.__test__ = False  # type: ignore[attr-defined]


def create_issue_for_project_integration(
    project_integration: ProjectIntegration,
    summary: str,
    description: Optional[str] = None,
    issue_type: Optional[str] = None,
    labels: Optional[List[str]] = None,
    milestone: Optional[str] = None,
    priority: Optional[str] = None,
    custom_fields: Optional[Dict[str, Any]] = None,
    *,
    assignee_user_id: Optional[int] = None,
    creator_user_id: Optional[int] = None,
) -> IssuePayload:
    integration = project_integration.integration
    if integration is None:
        raise IssueSyncError(
            "Project integration is missing associated tenant integration."
        )

    provider_key = integration.provider.lower()
    creator = CREATE_PROVIDER_REGISTRY.get(provider_key)
    if creator is None:
        raise IssueSyncError(
            f"Issue creation is not supported for provider '{integration.provider}'."
        )

    request = IssueCreateRequest(
        summary=summary,
        description=description,
        issue_type=issue_type,
        labels=list(labels) if labels is not None else None,
        milestone=milestone,
        priority=priority,
        custom_fields=dict(custom_fields) if custom_fields is not None else None,
    )

    # Get effective integration with user-specific credentials if creator_user_id is provided
    # This ensures issues are created with the correct user's credentials
    from .utils import get_effective_integration
    effective_integration = get_effective_integration(
        integration, project_integration, creator_user_id
    )

    # Resolve assignee from user identity mapping if provided
    assignee_username: Optional[str] = None
    assignee_account_id: Optional[str] = None
    if assignee_user_id is not None:
        from ..user_identity_service import (
            resolve_github_username,
            resolve_gitlab_username,
            resolve_jira_account_id,
        )

        if provider_key == "github":
            assignee_username = resolve_github_username(assignee_user_id)
            if not assignee_username:
                current_app.logger.warning(
                    f"User {assignee_user_id} has no GitHub username mapped. "
                    "Issue will be created without assignee."
                )
        elif provider_key == "gitlab":
            assignee_username = resolve_gitlab_username(assignee_user_id)
            if not assignee_username:
                current_app.logger.warning(
                    f"User {assignee_user_id} has no GitLab username mapped. "
                    "Issue will be created without assignee."
                )
        elif provider_key == "jira":
            assignee_account_id = resolve_jira_account_id(assignee_user_id)
            if not assignee_account_id:
                current_app.logger.warning(
                    f"User {assignee_user_id} has no Jira account ID mapped. "
                    "Issue will be created without assignee."
                )

    # Resolve creator from user identity mapping if provided
    creator_username: Optional[str] = None
    creator_account_id: Optional[str] = None
    if creator_user_id is not None:
        if provider_key == "github":
            creator_username = resolve_github_username(creator_user_id)
            if not creator_username:
                current_app.logger.warning(
                    f"User {creator_user_id} has no GitHub username mapped. "
                    "Issue will be created without attribution."
                )
        elif provider_key == "gitlab":
            creator_username = resolve_gitlab_username(creator_user_id)
            if not creator_username:
                current_app.logger.warning(
                    f"User {creator_user_id} has no GitLab username mapped. "
                    "Issue will be created without attribution."
                )
        elif provider_key == "jira":
            creator_account_id = resolve_jira_account_id(creator_user_id)
            if not creator_account_id:
                current_app.logger.warning(
                    f"User {creator_user_id} has no Jira account ID mapped. "
                    "Issue will be created without attribution."
                )

    try:
        # Call the provider's create_issue function with appropriate assignee and creator parameters
        # Use effective_integration to ensure correct user credentials are used
        if provider_key == "jira":
            return creator(  # type: ignore[call-arg]
                effective_integration,
                project_integration,
                request,
                assignee_account_id=assignee_account_id,
                creator_user_id=creator_user_id,
            )
        else:  # GitHub or GitLab
            return creator(  # type: ignore[call-arg]
                effective_integration, project_integration, request, assignee=assignee_username,
                creator_user_id=creator_user_id
            )
    except IssueSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception(
            "Issue creation failed for project_integration=%s provider=%s",
            project_integration.id,
            provider_key,
        )
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
