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
from .utils import ensure_base_url, get_timeout, parse_datetime

DEFAULT_FIELDS = [
    "summary",
    "status",
    "assignee",
    "updated",
    "labels",
    "description",
    "comment",
]
DEFAULT_EXPAND = ["renderedFields"]
DEFAULT_ISSUE_TYPE = "Task"
DEFAULT_CLOSE_TRANSITIONS = [
    "done",
    "closed",
    "close issue",
    "resolve issue",
    "resolved",
    "complete",
]


MAX_COMMENTS_PER_ISSUE = 20


def _issue_to_payload(base_url: str, issue: dict) -> IssuePayload:
    key = issue.get("key")
    if not key:
        raise IssueSyncError("Jira issue payload is missing an issue key.")
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    labels_source = (
        fields.get("labels") if isinstance(fields.get("labels"), list) else []
    )
    labels = [str(label) for label in labels_source]  # type: ignore[union-attr]
    return IssuePayload(
        external_id=str(key),
        title=str(fields.get("summary", "")),
        status=_resolve_status(fields),
        assignee=_resolve_assignee(fields),
        url=f"{base_url}/browse/{key}",
        labels=labels,
        external_updated_at=parse_datetime(fields.get("updated")),
        raw=issue,
        comments=_extract_comment_payloads(fields),
    )


def fetch_issues(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    since: Optional[datetime] = None,
) -> List[IssuePayload]:
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    jql = project_integration.config.get("jql") if project_integration.config else None
    if not jql:
        project_key = project_integration.external_identifier
        if not project_key:
            raise IssueSyncError("Jira project integration needs a project key or JQL.")
        jql = f'project = "{project_key}"'

    if since:
        since_value = _format_jira_datetime(since)
        jql = f'{jql} AND updated >= "{since_value}"'

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )
        data = client.search_issues(
            jql,
            startAt=0,
            maxResults=100,
            fields=",".join(DEFAULT_FIELDS),
            expand=",".join(DEFAULT_EXPAND),
            validate_query=True,
            json_result=True,
        )
    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover - unexpected failures
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    issues = data.get("issues", [])
    if not isinstance(issues, list):
        raise IssueSyncError("Unexpected Jira response payload.")

    payloads: List[IssuePayload] = []
    for issue in issues:
        key = issue.get("key")
        if not key:
            continue
        try:
            payloads.append(_issue_to_payload(base_url, issue))  # type: ignore[arg-type]
        except IssueSyncError:
            continue
    return payloads


def create_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    request: IssueCreateRequest,
    *,
    assignee_account_id: str | None = None,
    creator_user_id: int | None = None,
    creator_username: str | None = None,
) -> IssuePayload:
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    project_key = (project_integration.external_identifier or "").strip()
    if not project_key:
        raise IssueSyncError(
            "Jira project integration needs a project key for issue creation."
        )

    summary = (request.summary or "").strip()
    if not summary:
        raise IssueSyncError("Issue summary is required.")

    config: dict[str, Any] = project_integration.config or {}  # type: ignore[assignment]
    issue_type = (
        request.issue_type or config.get("issue_type") or DEFAULT_ISSUE_TYPE
    ).strip()
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    if request.description:
        fields["description"] = request.description
    if request.labels:
        fields["labels"] = request.labels
    if request.priority:
        priority_name = request.priority.strip()
        if priority_name:
            fields["priority"] = {"name": priority_name}
    if assignee_account_id:
        # Jira requires accountId for assignee
        fields["assignee"] = {"accountId": assignee_account_id}
    if request.custom_fields:
        for field_id, value in request.custom_fields.items():
            if value is None:
                continue
            key = str(field_id).strip()
            if not key:
                continue
            fields[key] = value

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )
        created_issue = client.create_issue(fields=fields)

        # Add attribution comment if creator information is provided
        # This helps track who actually requested the issue creation when using shared credentials
        if creator_username:
            try:
                # Jira uses accountId for @mentions, but we'll use the account ID from UserIdentityMap
                # Format: _Created via aiops by [~accountId]_
                attribution = f"_Created via aiops by [~{creator_username}]_"
                client.add_comment(created_issue.key, attribution)
            except Exception as exc:  # noqa: BLE001
                # Don't fail the whole operation if commenting fails
                from flask import current_app
                current_app.logger.warning(
                    f"Failed to add attribution comment to issue {created_issue.key}: {exc}"
                )

        issue_data = getattr(created_issue, "raw", None)
        if not isinstance(issue_data, dict) or "fields" not in issue_data:
            fetched_issue = client.issue(
                created_issue.key,
                fields=",".join(DEFAULT_FIELDS),
                expand=",".join(DEFAULT_EXPAND),
            )
            issue_data = getattr(fetched_issue, "raw", None)
        if not isinstance(issue_data, dict):
            raise IssueSyncError("Jira did not return expected issue payload.")
        return _issue_to_payload(base_url, issue_data)
    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover - unexpected failures
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def create_comment(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    issue_key: str,
    body: str,
) -> IssueCommentPayload:
    """Add a comment to a Jira issue.

    Args:
        integration: TenantIntegration for Jira
        project_integration: ProjectIntegration for the project
        issue_key: Jira issue key (e.g., "PROJ-123")
        body: Comment text to add

    Returns:
        IssueCommentPayload with comment details

    Raises:
        IssueSyncError: If comment creation fails
    """
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    issue_key = (issue_key or "").strip()
    if not issue_key:
        raise IssueSyncError("Jira issue key is required for adding a comment.")

    body = (body or "").strip()
    if not body:
        raise IssueSyncError("Comment body is required.")

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )
        comment = client.add_comment(issue_key, body)

        # Extract comment details
        author_raw = getattr(comment, "author", None)
        author_name = None
        if author_raw:
            author_name = getattr(author_raw, "displayName", None) or getattr(
                author_raw, "name", None
            )

        created_value = getattr(comment, "updated", None) or getattr(comment, "created", None)
        comment_id = getattr(comment, "id", None)

        return IssueCommentPayload(
            author=str(author_name) if author_name else None,
            body=getattr(comment, "body", "") or "",
            created_at=parse_datetime(created_value),
            url=None,
            id=str(comment_id) if comment_id else None,
        )
    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover - unexpected failures
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def update_comment(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    issue_key: str,
    comment_id: str,
    body: str,
) -> IssueCommentPayload:
    """Update an existing comment on a Jira issue.

    Args:
        integration: Jira integration
        project_integration: Project integration
        issue_key: Issue key (e.g. 'IWFCLOUD2-42')
        comment_id: Comment ID to update
        body: New comment text

    Returns:
        Updated comment payload

    Raises:
        IssueSyncError: On API errors or missing configuration
    """
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    issue_key = (issue_key or "").strip()
    if not issue_key:
        raise IssueSyncError("Jira issue key is required for updating a comment.")

    comment_id = (comment_id or "").strip()
    if not comment_id:
        raise IssueSyncError("Comment ID is required for updating a comment.")

    body = (body or "").strip()
    if not body:
        raise IssueSyncError("Comment body is required.")

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )
        # Get the comment object
        comment = client.comment(issue_key, comment_id)
        # Update the comment body
        comment.update(body=body)

        # Extract updated comment details
        author_raw = getattr(comment, "author", None)
        author_name = None
        if author_raw:
            author_name = getattr(author_raw, "displayName", None) or getattr(
                author_raw, "name", None
            )

        created_value = getattr(comment, "updated", None) or getattr(comment, "created", None)
        comment_id = getattr(comment, "id", None)

        return IssueCommentPayload(
            author=str(author_name) if author_name else None,
            body=getattr(comment, "body", "") or "",
            created_at=parse_datetime(created_value),
            url=None,
            id=str(comment_id) if comment_id else None,
        )
    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover - unexpected failures
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def close_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    external_id: str,
) -> IssuePayload:
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    issue_key = (external_id or "").strip()
    if not issue_key:
        raise IssueSyncError("Jira issue identifier is required for closing an issue.")

    config: dict[str, Any] = project_integration.config or {}  # type: ignore[assignment]
    preferred_transition_name = (config.get("close_transition") or "").strip().lower()

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )
        transitions = client.transitions(issue_key)
        transition_id = _select_close_transition(transitions, preferred_transition_name)
        if transition_id is None:
            raise IssueSyncError(
                "Jira project configuration lacks a suitable transition to close issues."
            )
        client.transition_issue(issue_key, transition_id)
        issue = client.issue(issue_key, fields=",".join(DEFAULT_FIELDS))
        issue_data = getattr(issue, "raw", None)
        if not isinstance(issue_data, dict):
            raise IssueSyncError(
                "Jira did not return expected issue payload after closing."
            )
        return _issue_to_payload(base_url, issue_data)
    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover - unexpected failures
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def update_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    external_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    labels: Optional[List[str]] = None,
) -> IssuePayload:
    """Update a Jira issue.

    Args:
        integration: Jira integration
        project_integration: Project integration
        external_id: Issue key (e.g. 'PROJ-123')
        title: New summary/title (optional)
        description: New description (optional)
        labels: New labels list (optional)

    Returns:
        Updated IssuePayload

    Raises:
        IssueSyncError: If update fails
    """
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    issue_key = (external_id or "").strip()
    if not issue_key:
        raise IssueSyncError("Jira issue identifier is required.")

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )

        # Build update fields
        update_fields: dict[str, Any] = {}
        if title is not None:
            update_fields["summary"] = title
        if description is not None:
            update_fields["description"] = description
        if labels is not None:
            update_fields["labels"] = labels

        if update_fields:
            issue = client.issue(issue_key)
            issue.update(fields=update_fields)

        # Fetch updated issue
        issue = client.issue(issue_key, fields=",".join(DEFAULT_FIELDS))
        issue_data = getattr(issue, "raw", None)
        if not isinstance(issue_data, dict):
            raise IssueSyncError("Jira did not return expected issue payload.")
        return _issue_to_payload(base_url, issue_data)

    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass


def reopen_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    external_id: str,
) -> IssuePayload:
    """Reopen a closed Jira issue.

    Args:
        integration: Jira integration
        project_integration: Project integration
        external_id: Issue key (e.g. 'PROJ-123')

    Returns:
        Updated IssuePayload

    Raises:
        IssueSyncError: If reopen fails
    """
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    issue_key = (external_id or "").strip()
    if not issue_key:
        raise IssueSyncError("Jira issue identifier is required.")

    config: dict[str, Any] = project_integration.config or {}  # type: ignore[assignment]
    preferred_transition_name = (config.get("reopen_transition") or "").strip().lower()

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )
        transitions = client.transitions(issue_key)

        # Find reopen transition (commonly "Reopen" or "To Do")
        transition_id = None
        for transition in transitions:
            name = transition.get("name", "").lower()
            to_status = transition.get("to", {})
            to_name = to_status.get("name", "").lower() if isinstance(to_status, dict) else ""

            # Check for preferred transition name
            if preferred_transition_name and preferred_transition_name in name:
                transition_id = transition["id"]
                break
            # Check for common reopen transitions
            if "reopen" in name or "to do" in name or "open" in to_name:
                transition_id = transition["id"]
                break

        if transition_id is None:
            raise IssueSyncError(
                "Jira project lacks a suitable transition to reopen issues. "
                "Configure 'reopen_transition' in project settings."
            )

        client.transition_issue(issue_key, transition_id)
        issue = client.issue(issue_key, fields=",".join(DEFAULT_FIELDS))
        issue_data = getattr(issue, "raw", None)
        if not isinstance(issue_data, dict):
            raise IssueSyncError("Jira did not return expected issue payload.")
        return _issue_to_payload(base_url, issue_data)

    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass


def assign_issue(
    integration: Any,  # TenantIntegration or IntegrationLike
    project_integration: ProjectIntegration,
    external_id: str,
    assignee_account_id: str,
) -> IssuePayload:
    """Assign a Jira issue to a user.

    Args:
        integration: Jira integration
        project_integration: Project integration
        external_id: Issue key (e.g. 'PROJ-123')
        assignee_account_id: Jira account ID of assignee

    Returns:
        Updated IssuePayload

    Raises:
        IssueSyncError: If assignment fails
    """
    base_url = integration.base_url  # type: ignore[assignment]
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)  # type: ignore[arg-type]

    settings: dict[str, Any] = integration.settings or {}  # type: ignore[assignment]
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    issue_key = (external_id or "").strip()
    if not issue_key:
        raise IssueSyncError("Jira issue identifier is required.")

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,  # type: ignore[arg-type]
            basic_auth=(username, integration.api_token),  # type: ignore[arg-type]
            timeout=timeout,
        )

        # Assign the issue
        client.assign_issue(issue_key, assignee_account_id)

        # Fetch updated issue
        issue = client.issue(issue_key, fields=",".join(DEFAULT_FIELDS))
        issue_data = getattr(issue, "raw", None)
        if not isinstance(issue_data, dict):
            raise IssueSyncError("Jira did not return expected issue payload.")
        return _issue_to_payload(base_url, issue_data)

    except JIRAError as exc:
        message = getattr(exc, "text", None) or str(exc)
        raise IssueSyncError(f"Jira API error: {message}") from exc
    except Exception as exc:  # pragma: no cover
        error_msg = str(exc) or f"Unknown error: {type(exc).__name__}"
        raise IssueSyncError(error_msg) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover
                pass


def _resolve_assignee(fields: dict) -> Optional[str]:
    from .utils import normalize_assignee_name

    assignee = fields.get("assignee")
    if isinstance(assignee, dict):
        value = assignee.get("displayName") or assignee.get("name")
        return normalize_assignee_name(str(value) if value else None)
    return None


def _resolve_status(fields: dict) -> Optional[str]:
    status = fields.get("status")
    if isinstance(status, dict):
        name = status.get("name")
        return str(name) if name else None
    return None


def _extract_comment_payloads(fields: dict) -> List[IssueCommentPayload]:
    comments: List[IssueCommentPayload] = []
    block = fields.get("comment")
    entries = block.get("comments") if isinstance(block, dict) else None
    if not isinstance(entries, list):
        return comments
    for entry in reversed(entries):
        author_raw = entry.get("author") if isinstance(entry, dict) else None
        author_name = None
        if isinstance(author_raw, dict):
            author_name = author_raw.get("displayName") or author_raw.get("name")
        created_value = entry.get("updated") or entry.get("created")
        comment_id = entry.get("id")  # Extract comment ID
        comments.append(
            IssueCommentPayload(
                author=str(author_name) if author_name else None,
                body=str(entry.get("body") or ""),
                created_at=parse_datetime(created_value),
                url=None,
                id=str(comment_id) if comment_id else None,
            )
        )
        if len(comments) >= MAX_COMMENTS_PER_ISSUE:
            break
    return comments


def _format_jira_datetime(source: datetime) -> str:
    if source.tzinfo is None:
        aware = source.replace(tzinfo=timezone.utc)
    else:
        aware = source.astimezone(timezone.utc)
    return aware.strftime("%Y-%m-%d %H:%M")


def _select_close_transition(
    transitions: List[dict[str, Any]], preferred_name: str
) -> Optional[str]:
    candidates = []
    if preferred_name:
        candidates.append(preferred_name)
    candidates.extend(DEFAULT_CLOSE_TRANSITIONS)

    lower_candidates = [name.lower() for name in candidates]
    for transition in transitions or []:
        name = str(transition.get("name") or "").strip().lower()
        if not name:
            continue
        if name in lower_candidates:
            identifier = transition.get("id")
            if identifier:
                return str(identifier)
    return None
