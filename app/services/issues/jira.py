from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from ...models import ProjectIntegration, TenantIntegration
from . import IssueCreateRequest, IssuePayload, IssueSyncError
from .utils import ensure_base_url, get_timeout, parse_datetime

DEFAULT_FIELDS = ["summary", "status", "assignee", "updated", "labels", "description"]
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
    labels = [str(label) for label in labels_source]
    return IssuePayload(
        external_id=str(key),
        title=str(fields.get("summary", "")),
        status=_resolve_status(fields),
        assignee=_resolve_assignee(fields),
        url=f"{base_url}/browse/{key}",
        labels=labels,
        external_updated_at=parse_datetime(fields.get("updated")),
        raw=issue,
    )


def fetch_issues(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    since: Optional[datetime] = None,
) -> List[IssuePayload]:
    base_url = integration.base_url
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)

    settings = integration.settings or {}
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
        from jira import JIRA, JIRAError  # type: ignore import-not-found
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,
            basic_auth=(username, integration.api_token),
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
        raise IssueSyncError(str(exc)) from exc
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
            payloads.append(_issue_to_payload(base_url, issue))
        except IssueSyncError:
            continue
    return payloads


def create_issue(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    request: IssueCreateRequest,
) -> IssuePayload:
    base_url = integration.base_url
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)

    settings = integration.settings or {}
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

    config = project_integration.config or {}
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

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore import-not-found
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,
            basic_auth=(username, integration.api_token),
            timeout=timeout,
        )
        created_issue = client.create_issue(fields=fields)
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
        raise IssueSyncError(str(exc)) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def close_issue(
    integration: TenantIntegration,
    project_integration: ProjectIntegration,
    external_id: str,
) -> IssuePayload:
    base_url = integration.base_url
    if not base_url:
        raise IssueSyncError("Jira integration requires a base URL.")
    base_url = ensure_base_url(integration, base_url)

    settings = integration.settings or {}
    username = (settings.get("username") or "").strip()
    if not username:
        raise IssueSyncError("Jira integration requires an account email.")

    issue_key = (external_id or "").strip()
    if not issue_key:
        raise IssueSyncError("Jira issue identifier is required for closing an issue.")

    config = project_integration.config or {}
    preferred_transition_name = (config.get("close_transition") or "").strip().lower()

    timeout = get_timeout(integration)
    try:
        from jira import JIRA, JIRAError  # type: ignore import-not-found
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        missing = getattr(exc, "name", None) or "jira"
        raise IssueSyncError(
            f"Jira support requires the '{missing}' package. Install dependencies with 'make sync' or 'uv pip install jira'."
        ) from exc

    client: Optional[Any] = None
    try:
        client = JIRA(
            server=base_url,
            basic_auth=(username, integration.api_token),
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
        raise IssueSyncError(str(exc)) from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def _resolve_assignee(fields: dict) -> Optional[str]:
    assignee = fields.get("assignee")
    if isinstance(assignee, dict):
        value = assignee.get("displayName") or assignee.get("name")
        return str(value) if value else None
    return None


def _resolve_status(fields: dict) -> Optional[str]:
    status = fields.get("status")
    if isinstance(status, dict):
        name = status.get("name")
        return str(name) if name else None
    return None


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
