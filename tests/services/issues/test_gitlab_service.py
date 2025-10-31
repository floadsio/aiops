from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.issues import IssueCreateRequest, IssueSyncError
from app.services.issues import gitlab as gitlab_service


class FakeIssue:
    def __init__(self, **kwargs):
        self.attributes = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


def _install_fake_client(monkeypatch, *, issues=None, created_issue=None):
    issues = issues or []

    project = SimpleNamespace()

    def list_wrapper(**_):
        return issues

    def create_wrapper(payload):
        if created_issue:
            return created_issue(payload)
        data = {
            "id": 1,
            "title": payload.get("title"),
            "state": "opened",
            "web_url": "https://gitlab.example/project/-/issues/1",
            "labels": payload.get("labels") or [],
            "updated_at": datetime(2024, 10, 1, tzinfo=timezone.utc).isoformat(),
            "assignee": None,
        }
        return FakeIssue(**data)

    project.issues = SimpleNamespace(list=list_wrapper, create=create_wrapper)

    class FakeProjects:
        def __init__(self, project_ref):
            self._project = project_ref

        def get(self, _):
            return self._project

    fake_client = SimpleNamespace(projects=FakeProjects(project))

    monkeypatch.setattr("app.services.issues.gitlab._build_client", lambda integration, base_url=None: fake_client)


def test_fetch_issues(monkeypatch):
    issues = [
        FakeIssue(
            id=101,
            title="Fix CI",
            state="opened",
            web_url="https://gitlab.example/project/-/issues/101",
            updated_at="2024-10-10T12:00:00Z",
            labels=["ci"],
            assignee={"name": "Dev", "username": "dev"},
        )
    ]

    _install_fake_client(monkeypatch, issues=issues)

    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(external_identifier="group/project", config={})

    payloads = gitlab_service.fetch_issues(integration, project_integration)

    assert len(payloads) == 1
    issue = payloads[0]
    assert issue.external_id == "101"
    assert issue.assignee == "Dev"


def test_create_issue(monkeypatch):
    def created_issue(payload):
        data = {
            "id": 42,
            "title": payload.get("title"),
            "state": "opened",
            "web_url": "https://gitlab.example/project/-/issues/42",
            "labels": payload.get("labels") or [],
            "updated_at": "2024-10-11T10:00:00Z",
            "assignee": None,
        }
        return FakeIssue(**data)

    _install_fake_client(monkeypatch, issues=[], created_issue=lambda payload: created_issue(payload))

    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(external_identifier="group/project", config={})

    request = IssueCreateRequest(summary="Add pipeline", description="Automate", labels=["ci"])
    payload = gitlab_service.create_issue(integration, project_integration, request)

    assert payload.external_id == "42"
    assert payload.title == "Add pipeline"
    assert payload.labels == ["ci"]


def test_create_issue_requires_summary():
    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(external_identifier="group/project", config={})

    with pytest.raises(IssueSyncError):
        gitlab_service.create_issue(
            integration,
            project_integration,
            IssueCreateRequest(summary=""),
        )
