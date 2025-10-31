from __future__ import annotations

from datetime import datetime, timezone
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Dict

import pytest

from app.services.issues import IssueCreateRequest, IssueSyncError
from app.services.issues import jira as jira_service


def _install_fake_jira(monkeypatch, jira_class):
    module = ModuleType("jira")

    class FakeJIRAError(Exception):
        def __init__(self, text=""):
            super().__init__(text)
            self.text = text

    module.JIRA = jira_class
    module.JIRAError = FakeJIRAError
    monkeypatch.setitem(sys.modules, "jira", module)
    return FakeJIRAError


def test_fetch_issues_uses_jira_client(monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeJIRA:
        def __init__(self, server: str, basic_auth: tuple[str, str], timeout: float):
            captured["server"] = server
            captured["basic_auth"] = basic_auth
            captured["timeout"] = timeout

        def search_issues(
            self,
            jql_str: str,
            *,
            startAt: int,
            maxResults: int,
            fields: str,
            validate_query: bool,
            json_result: bool,
        ) -> Dict[str, Any]:
            captured["jql"] = jql_str
            captured["startAt"] = startAt
            captured["maxResults"] = maxResults
            captured["fields"] = fields
            captured["validate_query"] = validate_query
            captured["json_result"] = json_result
            return {
                "issues": [
                    {
                        "key": "DEVOPS-1",
                        "fields": {
                            "summary": "Fix pipeline",
                            "status": {"name": "Done"},
                            "assignee": {"displayName": "Ivo"},
                            "updated": "2024-10-01T12:34:00.000+0000",
                            "labels": ["infra"],
                        },
                    }
                ]
            }

        def close(self):
            captured["closed"] = True

    _install_fake_jira(monkeypatch, FakeJIRA)

    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={"username": "user@example.com"},
    )
    project_integration = SimpleNamespace(
        config={},
        external_identifier="DEVOPS",
    )

    results = jira_service.fetch_issues(integration, project_integration)

    assert captured["server"] == "https://example.atlassian.net"
    assert captured["basic_auth"] == ("user@example.com", "token-123")
    assert captured["timeout"] is not None
    assert captured["jql"] == 'project = "DEVOPS"'
    assert captured["fields"] == ",".join(jira_service.DEFAULT_FIELDS)
    assert captured["closed"] is True
    assert len(results) == 1
    issue = results[0]
    assert issue.external_id == "DEVOPS-1"
    assert issue.status == "Done"
    assert issue.assignee == "Ivo"
    assert issue.labels == ["infra"]


def test_fetch_issues_with_since(monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def search_issues(self, jql_str: str, **kwargs: Any) -> Dict[str, Any]:
            captured["jql"] = jql_str
            return {"issues": []}

        def close(self):
            pass

    _install_fake_jira(monkeypatch, FakeJIRA)

    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={"username": "user@example.com"},
    )
    project_integration = SimpleNamespace(
        config={},
        external_identifier="DEVOPS",
    )

    since = datetime(2024, 9, 1, 15, 30, tzinfo=timezone.utc)
    jira_service.fetch_issues(integration, project_integration, since=since)

    assert 'updated >= "' in captured["jql"]
    assert "2024-09-01 15:30" in captured["jql"]


def test_fetch_issues_without_username():
    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={},
    )
    project_integration = SimpleNamespace(
        config={},
        external_identifier="DEVOPS",
    )

    with pytest.raises(IssueSyncError):
        jira_service.fetch_issues(integration, project_integration)


def test_create_issue_uses_jira_client(monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeIssue:
        def __init__(self, key: str, raw: Dict[str, Any]):
            self.key = key
            self.raw = raw

    class FakeJIRA:
        def __init__(self, server: str, basic_auth: tuple[str, str], timeout: float):
            captured["server"] = server
            captured["basic_auth"] = basic_auth
            captured["timeout"] = timeout

        def create_issue(self, fields: Dict[str, Any]) -> FakeIssue:
            captured["create_fields"] = fields
            return FakeIssue(
                "DEVOPS-2",
                {
                    "key": "DEVOPS-2",
                    "fields": {
                        "summary": fields["summary"],
                        "status": {"name": "To Do"},
                        "assignee": None,
                        "updated": "2024-10-15T12:00:00.000+0000",
                        "labels": fields.get("labels", []),
                    },
                },
            )

        def issue(self, *args, **kwargs):
            captured["issue_invoked"] = True
            return FakeIssue(
                "DEVOPS-2",
                {
                    "key": "DEVOPS-2",
                    "fields": {
                        "summary": "ignored",
                        "status": {"name": "To Do"},
                        "assignee": {"displayName": "Alice"},
                        "updated": "2024-10-15T12:00:00.000+0000",
                        "labels": ["infra"],
                    },
                },
            )

        def close(self):
            captured["closed"] = True

    _install_fake_jira(monkeypatch, FakeJIRA)

    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={"username": "user@example.com"},
    )
    project_integration = SimpleNamespace(
        config={},
        external_identifier="DEVOPS",
    )

    request = IssueCreateRequest(
        summary="Create new pipeline task",
        description="Automate the deployment.",
        labels=["automation"],
    )
    payload = jira_service.create_issue(integration, project_integration, request)

    assert captured["server"] == "https://example.atlassian.net"
    assert captured["basic_auth"] == ("user@example.com", "token-123")
    assert captured["timeout"] is not None
    assert captured["create_fields"]["project"] == {"key": "DEVOPS"}
    assert captured["create_fields"]["summary"] == "Create new pipeline task"
    assert captured["create_fields"]["issuetype"]["name"] == jira_service.DEFAULT_ISSUE_TYPE
    assert captured["create_fields"]["labels"] == ["automation"]
    assert "issue_invoked" not in captured
    assert captured["closed"] is True
    assert payload.external_id == "DEVOPS-2"
    assert payload.title == "Create new pipeline task"
    assert payload.labels == ["automation"]


def test_create_issue_fetches_when_raw_missing(monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeIssue:
        def __init__(self, key: str, raw: Dict[str, Any] | None):
            self.key = key
            self.raw = raw

    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def create_issue(self, fields: Dict[str, Any]) -> FakeIssue:
            captured["create_fields"] = fields
            return FakeIssue("DEVOPS-3", {"key": "DEVOPS-3"})

        def issue(self, key: str, fields: str):
            captured["issue_fields"] = fields
            return FakeIssue(
                key,
                {
                    "key": key,
                    "fields": {
                        "summary": "Created via API",
                        "status": {"name": "In Progress"},
                        "assignee": {"displayName": "Bob"},
                        "updated": "2024-11-01T09:30:00.000+0000",
                        "labels": ["ops"],
                    },
                },
            )

        def close(self):
            pass

    _install_fake_jira(monkeypatch, FakeJIRA)

    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={"username": "user@example.com"},
    )
    project_integration = SimpleNamespace(
        config={},
        external_identifier="DEVOPS",
    )

    request = IssueCreateRequest(summary="Created via API")
    payload = jira_service.create_issue(integration, project_integration, request)

    assert captured["create_fields"]["project"] == {"key": "DEVOPS"}
    assert captured["issue_fields"] == ",".join(jira_service.DEFAULT_FIELDS)
    assert payload.external_id == "DEVOPS-3"
    assert payload.status == "In Progress"
    assert payload.assignee == "Bob"
    assert payload.labels == ["ops"]


def test_create_issue_requires_summary(monkeypatch):
    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    _install_fake_jira(monkeypatch, FakeJIRA)

    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={"username": "user@example.com"},
    )
    project_integration = SimpleNamespace(
        config={},
        external_identifier="DEVOPS",
    )

    with pytest.raises(IssueSyncError):
        jira_service.create_issue(integration, project_integration, IssueCreateRequest(summary=""))
