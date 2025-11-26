from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List

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

    class FakeComment:
        def __init__(self, comment_id: str, author_name: str, body: str, created: str):
            self.id = comment_id
            self.author = SimpleNamespace(displayName=author_name)
            self.body = body
            self.created = created
            self.updated = created
            self.raw = {
                "id": comment_id,
                "author": {"displayName": author_name},
                "body": body,
                "created": created,
                "updated": created,
            }

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
            expand: str = "",
        ) -> Dict[str, Any]:
            captured["jql"] = jql_str
            captured["startAt"] = startAt
            captured["maxResults"] = maxResults
            captured["fields"] = fields
            captured["validate_query"] = validate_query
            captured["json_result"] = json_result
            captured["expand"] = expand
            return {
                "issues": [
                    {
                        "key": "DEVOPS-1",
                        "fields": {
                            "summary": "Fix pipeline",
                            "status": {"name": "Done"},
                            "assignee": {"displayName": "Example User"},
                            "updated": "2024-10-01T12:34:00.000+0000",
                            "labels": ["infra"],
                        },
                    }
                ]
            }

        def comments(self, issue_key: str) -> List[Any]:
            captured["comments_fetched_for"] = issue_key
            return []

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
    assert issue.assignee == "Example User"
    assert issue.labels == ["infra"]


def test_fetch_issues_with_since(monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def search_issues(self, jql_str: str, **kwargs: Any) -> Dict[str, Any]:
            captured["jql"] = jql_str
            return {"issues": []}

        def comments(self, issue_key: str) -> List[Any]:
            return []

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

        def comments(self, issue_key: str) -> List[Any]:
            return []

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
        priority="High",
        custom_fields={"customfield_10011": 5},
    )
    payload = jira_service.create_issue(integration, project_integration, request)

    assert captured["server"] == "https://example.atlassian.net"
    assert captured["basic_auth"] == ("user@example.com", "token-123")
    assert captured["timeout"] is not None
    assert captured["create_fields"]["project"] == {"key": "DEVOPS"}
    assert captured["create_fields"]["summary"] == "Create new pipeline task"
    assert (
        captured["create_fields"]["issuetype"]["name"]
        == jira_service.DEFAULT_ISSUE_TYPE
    )
    assert captured["create_fields"]["labels"] == ["automation"]
    assert captured["create_fields"]["priority"] == {"name": "High"}
    assert captured["create_fields"]["customfield_10011"] == 5
    assert "issue_invoked" not in captured
    assert captured["closed"] is True
    assert payload.external_id == "DEVOPS-2"
    assert payload.title == "Create new pipeline task"
    assert payload.labels == ["automation"]


def test_close_issue_uses_transition(monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeJIRA:
        def __init__(self, server: str, basic_auth: tuple[str, str], timeout: float):
            captured["server"] = server
            captured["basic_auth"] = basic_auth
            captured["timeout"] = timeout

        def transitions(self, issue_key: str) -> List[Dict[str, Any]]:
            captured["transitions_key"] = issue_key
            return [
                {"id": "20", "name": "In Progress"},
                {"id": "30", "name": "Done"},
            ]

        def transition_issue(self, issue_key: str, transition_id: str):
            captured["transition_issue_key"] = issue_key
            captured["transition_id"] = transition_id

        def issue(self, issue_key: str, fields: str):
            captured["issue_fields"] = fields
            return SimpleNamespace(
                raw={
                    "key": issue_key,
                    "fields": {
                        "summary": "Legacy cleanup",
                        "status": {"name": "Done"},
                        "assignee": None,
                        "updated": "2024-10-15T12:00:00.000+0000",
                        "labels": ["cleanup"],
                    },
                }
            )

        def comments(self, issue_key: str) -> List[Any]:
            return []

        def close(self):
            captured["closed"] = True

    _install_fake_jira(monkeypatch, FakeJIRA)

    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={"username": "user@example.com"},
    )
    project_integration = SimpleNamespace(config={}, external_identifier="DEVOPS")

    payload = jira_service.close_issue(integration, project_integration, "DEVOPS-10")

    assert captured["transition_issue_key"] == "DEVOPS-10"
    assert captured["transition_id"] == "30"
    assert "summary" in captured["issue_fields"]
    assert captured.get("closed") is True
    assert payload.external_id == "DEVOPS-10"
    assert payload.status == "Done"


def test_close_issue_requires_transition(monkeypatch):
    class FakeJIRA:
        def __init__(self, *_args, **_kwargs):
            pass

        def transitions(self, issue_key: str) -> List[Dict[str, Any]]:
            return [{"id": "10", "name": "Review"}]

        def comments(self, issue_key: str) -> List[Any]:
            return []

        def close(self):
            pass

    _install_fake_jira(monkeypatch, FakeJIRA)

    integration = SimpleNamespace(
        base_url="https://example.atlassian.net",
        api_token="token-123",
        settings={"username": "user@example.com"},
    )
    project_integration = SimpleNamespace(config={}, external_identifier="DEVOPS")

    with pytest.raises(IssueSyncError):
        jira_service.close_issue(integration, project_integration, "DEVOPS-11")


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

        def issue(self, key: str, fields: str, expand: str = ""):
            captured["issue_fields"] = fields
            captured["issue_expand"] = expand
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

        def comments(self, issue_key: str) -> List[Any]:
            return []

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

        def comments(self, issue_key: str) -> List[Any]:
            return []

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
        jira_service.create_issue(
            integration, project_integration, IssueCreateRequest(summary="")
        )


def test_fetch_issues_includes_comments(monkeypatch):
    """Test that comments are fetched and included in issue payload."""
    captured: Dict[str, Any] = {}

    class FakeComment:
        def __init__(self, comment_id: str, author_name: str, body: str, created: str):
            self.id = comment_id
            self.author = SimpleNamespace(displayName=author_name)
            self.body = body
            self.created = created
            self.updated = created
            self.raw = {
                "id": comment_id,
                "author": {"displayName": author_name},
                "body": body,
                "created": created,
                "updated": created,
            }

    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def search_issues(self, jql_str: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "issues": [
                    {
                        "key": "DEVOPS-5",
                        "fields": {
                            "summary": "Fix bug",
                            "status": {"name": "Open"},
                            "assignee": None,
                            "updated": "2024-10-01T12:34:00.000+0000",
                            "labels": [],
                        },
                    }
                ]
            }

        def comments(self, issue_key: str) -> List[Any]:
            captured["comments_requested_for"] = issue_key
            return [
                FakeComment("10001", "Alice", "First comment", "2024-10-01T10:00:00.000+0000"),
                FakeComment("10002", "Bob", "Second comment", "2024-10-01T11:00:00.000+0000"),
            ]

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

    results = jira_service.fetch_issues(integration, project_integration)

    assert len(results) == 1
    issue = results[0]
    assert issue.external_id == "DEVOPS-5"
    assert captured["comments_requested_for"] == "DEVOPS-5"
    assert len(issue.comments) == 2
    # Comments are reversed by _extract_comment_payloads
    assert issue.comments[0].author == "Bob"
    assert issue.comments[0].body == "Second comment"
    assert issue.comments[1].author == "Alice"
    assert issue.comments[1].body == "First comment"


def test_fetch_issues_handles_comment_fetch_failure_gracefully(monkeypatch):
    """Test that issue sync continues if comment fetch fails."""
    captured: Dict[str, Any] = {}

    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def search_issues(self, jql_str: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "issues": [
                    {
                        "key": "DEVOPS-6",
                        "fields": {
                            "summary": "Test issue",
                            "status": {"name": "Open"},
                            "assignee": None,
                            "updated": "2024-10-01T12:34:00.000+0000",
                            "labels": [],
                        },
                    }
                ]
            }

        def comments(self, issue_key: str) -> List[Any]:
            captured["comments_attempted"] = True
            raise Exception("Failed to fetch comments")

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

    results = jira_service.fetch_issues(integration, project_integration)

    assert captured.get("comments_attempted") is True
    assert len(results) == 1
    assert results[0].external_id == "DEVOPS-6"
    assert results[0].comments == []  # No comments due to error, but issue still synced


def test_fetch_issues_limits_comments_per_issue(monkeypatch):
    """Test that only MAX_COMMENTS_PER_ISSUE comments are included."""
    class FakeComment:
        def __init__(self, comment_id: str):
            self.id = comment_id
            self.author = SimpleNamespace(displayName="User")
            self.body = f"Comment {comment_id}"
            self.created = "2024-10-01T10:00:00.000+0000"
            self.updated = "2024-10-01T10:00:00.000+0000"
            self.raw = {
                "id": comment_id,
                "author": {"displayName": "User"},
                "body": f"Comment {comment_id}",
                "created": "2024-10-01T10:00:00.000+0000",
                "updated": "2024-10-01T10:00:00.000+0000",
            }

    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def search_issues(self, jql_str: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "issues": [
                    {
                        "key": "DEVOPS-7",
                        "fields": {
                            "summary": "Many comments",
                            "status": {"name": "Open"},
                            "assignee": None,
                            "updated": "2024-10-01T12:34:00.000+0000",
                            "labels": [],
                        },
                    }
                ]
            }

        def comments(self, issue_key: str) -> List[Any]:
            # Return more comments than MAX_COMMENTS_PER_ISSUE
            return [FakeComment(str(i)) for i in range(30)]

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

    results = jira_service.fetch_issues(integration, project_integration)

    assert len(results) == 1
    # Should be limited to MAX_COMMENTS_PER_ISSUE
    assert len(results[0].comments) == jira_service.MAX_COMMENTS_PER_ISSUE


def test_create_issue_fetches_comments(monkeypatch):
    """Test that comments are fetched when creating a new issue."""
    captured: Dict[str, Any] = {}

    class FakeComment:
        def __init__(self, comment_id: str, body: str):
            self.id = comment_id
            self.author = SimpleNamespace(displayName="System")
            self.body = body
            self.created = "2024-10-15T12:00:00.000+0000"
            self.updated = "2024-10-15T12:00:00.000+0000"
            self.raw = {
                "id": comment_id,
                "author": {"displayName": "System"},
                "body": body,
                "created": "2024-10-15T12:00:00.000+0000",
                "updated": "2024-10-15T12:00:00.000+0000",
            }

    class FakeIssue:
        def __init__(self, key: str, raw: Dict[str, Any]):
            self.key = key
            self.raw = raw

    class FakeJIRA:
        def __init__(self, *args, **kwargs):
            pass

        def create_issue(self, fields: Dict[str, Any]) -> FakeIssue:
            return FakeIssue(
                "DEVOPS-8",
                {
                    "key": "DEVOPS-8",
                    "fields": {
                        "summary": "New issue",
                        "status": {"name": "To Do"},
                        "assignee": None,
                        "updated": "2024-10-15T12:00:00.000+0000",
                        "labels": [],
                    },
                },
            )

        def comments(self, issue_key: str) -> List[Any]:
            captured["comments_for_created_issue"] = issue_key
            return [FakeComment("10001", "Attribution comment")]

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

    request = IssueCreateRequest(summary="New issue")
    payload = jira_service.create_issue(integration, project_integration, request)

    assert payload.external_id == "DEVOPS-8"
    assert captured["comments_for_created_issue"] == "DEVOPS-8"
    assert len(payload.comments) == 1
    assert payload.comments[0].body == "Attribution comment"
