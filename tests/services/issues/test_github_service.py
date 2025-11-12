from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List

import pytest

from app.services.issues import IssueCreateRequest, IssueSyncError
from app.services.issues import github as github_service

if "github" not in sys.modules:
    github_stub = types.ModuleType("github")

    class GithubExceptionStub(Exception):
        def __init__(self, status=None, *args, **kwargs):
            self.status = status
            super().__init__(status)

    github_stub.GithubException = GithubExceptionStub
    sys.modules["github"] = github_stub

    github_exception_module = types.ModuleType("github.GithubException")
    github_exception_module.GithubException = GithubExceptionStub
    sys.modules["github.GithubException"] = github_exception_module


class FakeGithubIssue:
    def __init__(
        self,
        number: int,
        title: str,
        state: str,
        html_url: str,
        labels=None,
        updated_at=None,
        assignee=None,
    ):
        self.number = number
        self.title = title
        self.state = state
        self.html_url = html_url
        self.labels = labels or []
        self.updated_at = updated_at or datetime(2024, 10, 10, tzinfo=timezone.utc)
        self.assignee = assignee
        self.pull_request = None
        self.raw_data = {"number": number}

    def edit(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class FakeRepo:
    def __init__(self, issues: List[FakeGithubIssue]):
        self._issues = issues
        self.created_payload = None
        self.closed_numbers: List[int] = []

    def get_issues(self, **_):
        return self._issues

    def create_issue(self, title, body=None, labels=None):
        issue = FakeGithubIssue(
            number=200,
            title=title,
            state="open",
            html_url="https://github.com/org/repo/issues/200",
            labels=labels or [],
            updated_at=datetime(2024, 10, 11, tzinfo=timezone.utc),
        )
        self.created_payload = {"title": title, "body": body, "labels": labels}
        return issue

    def get_issue(self, number):
        for issue in self._issues:
            if issue.number == number:
                self.closed_numbers.append(number)
                return issue
        raise IssueSyncError("Issue not found")


def _install_fake_client(monkeypatch, repo: FakeRepo):
    class FakeClient:
        def __init__(self, repository):
            self.repository = repository

        def get_repo(self, _):
            return self.repository

    fake_client = FakeClient(repo)
    monkeypatch.setattr(
        "app.services.issues.github._build_client",
        lambda integration, base_url=None: fake_client,
    )


def test_fetch_issues(monkeypatch):
    issues = [
        FakeGithubIssue(
            number=5,
            title="Fix bug",
            state="open",
            html_url="https://github.com/org/repo/issues/5",
            labels=[SimpleNamespace(name="bug")],
            assignee=SimpleNamespace(login="dev"),
        )
    ]
    repo = FakeRepo(issues)
    _install_fake_client(monkeypatch, repo)

    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(external_identifier="org/repo", config={})

    payloads = github_service.fetch_issues(integration, project_integration)

    assert len(payloads) == 1
    issue = payloads[0]
    assert issue.external_id == "5"
    assert issue.assignee == "dev"


def test_create_issue(monkeypatch):
    repo = FakeRepo([])
    _install_fake_client(monkeypatch, repo)

    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(external_identifier="org/repo", config={})

    request = IssueCreateRequest(
        summary="Add feature", description="Details", labels=["enhancement"]
    )
    payload = github_service.create_issue(integration, project_integration, request)

    assert repo.created_payload == {
        "title": "Add feature",
        "body": "Details",
        "labels": ["enhancement"],
    }
    assert payload.external_id == "200"
    assert payload.title == "Add feature"


def test_close_issue(monkeypatch):
    issue = FakeGithubIssue(
        number=42,
        title="Fix bug",
        state="open",
        html_url="https://github.com/org/repo/issues/42",
    )
    repo = FakeRepo([issue])
    _install_fake_client(monkeypatch, repo)

    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(external_identifier="org/repo", config={})

    payload = github_service.close_issue(integration, project_integration, "42")

    assert issue.state == "closed"
    assert payload.status == "closed"
    assert repo.closed_numbers.count(42) >= 2  # fetched before and after close


def test_create_issue_requires_summary():
    integration = SimpleNamespace(api_token="token", settings={}, base_url=None)
    project_integration = SimpleNamespace(external_identifier="org/repo", config={})

    with pytest.raises(IssueSyncError):
        github_service.create_issue(
            integration,
            project_integration,
            IssueCreateRequest(summary=""),
        )
