from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.issues import IssueCreateRequest, IssueSyncError
from app.services.issues import gitlab as gitlab_service

if "gitlab" not in sys.modules:
    gitlab_stub = types.ModuleType("gitlab")

    class GitlabErrorStub(Exception):
        pass

    class GitlabAuthenticationErrorStub(GitlabErrorStub):
        pass

    class GitlabGetErrorStub(GitlabErrorStub):
        pass

    class GitlabCreateErrorStub(GitlabErrorStub):
        pass

    gitlab_stub.Gitlab = object

    gitlab_exceptions_module = types.ModuleType("gitlab.exceptions")
    gitlab_exceptions_module.GitlabError = GitlabErrorStub
    gitlab_exceptions_module.GitlabAuthenticationError = GitlabAuthenticationErrorStub
    gitlab_exceptions_module.GitlabGetError = GitlabGetErrorStub
    gitlab_exceptions_module.GitlabCreateError = GitlabCreateErrorStub

    gitlab_stub.exceptions = gitlab_exceptions_module

    sys.modules["gitlab"] = gitlab_stub
    sys.modules["gitlab.exceptions"] = gitlab_exceptions_module


class FakeIssue:
    def __init__(self, **kwargs):
        self.attributes = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.state_event = None

    def save(self):
        if getattr(self, "state_event", None) == "close":
            self.state = "closed"
            if hasattr(self, "attributes"):
                self.attributes["state"] = "closed"


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

    def get_wrapper(identifier):
        for issue in issues:
            if str(getattr(issue, "id", "")) == str(identifier):
                return issue
        raise IssueSyncError("Issue not found")

    project.issues = SimpleNamespace(
        list=list_wrapper, create=create_wrapper, get=get_wrapper
    )

    class FakeProjects:
        def __init__(self, project_ref):
            self._project = project_ref

        def get(self, _):
            return self._project

    fake_client = SimpleNamespace(projects=FakeProjects(project))

    monkeypatch.setattr(
        "app.services.issues.gitlab._build_client",
        lambda integration, base_url=None: fake_client,
    )


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
    project_integration = SimpleNamespace(
        external_identifier="group/project", config={}
    )

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

    _install_fake_client(
        monkeypatch, issues=[], created_issue=lambda payload: created_issue(payload)
    )

    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(
        external_identifier="group/project", config={}
    )

    request = IssueCreateRequest(
        summary="Add pipeline", description="Automate", labels=["ci"]
    )
    payload = gitlab_service.create_issue(integration, project_integration, request)

    assert payload.external_id == "42"
    assert payload.title == "Add pipeline"
    assert payload.labels == ["ci"]


def test_close_issue(monkeypatch):
    issue = FakeIssue(
        id=77,
        title="Legacy cleanup",
        state="opened",
        web_url="https://gitlab.example/project/-/issues/77",
        updated_at="2024-10-12T12:00:00Z",
        labels=[],
    )

    _install_fake_client(monkeypatch, issues=[issue])

    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(
        external_identifier="group/project", config={}
    )

    payload = gitlab_service.close_issue(integration, project_integration, "77")

    assert issue.state == "closed"
    assert payload.status == "closed"


def test_create_issue_requires_summary():
    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(
        external_identifier="group/project", config={}
    )

    with pytest.raises(IssueSyncError):
        gitlab_service.create_issue(
            integration,
            project_integration,
            IssueCreateRequest(summary=""),
        )
