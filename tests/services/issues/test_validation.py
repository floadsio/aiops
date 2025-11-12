from __future__ import annotations

import sys
import types

import pytest
from requests.auth import HTTPBasicAuth

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

    class GitlabStub:
        def __init__(self, *_args, **_kwargs):
            pass

        def auth(self):
            return None

    gitlab_exceptions_module = types.ModuleType("gitlab.exceptions")
    gitlab_exceptions_module.GitlabError = GitlabErrorStub
    gitlab_exceptions_module.GitlabAuthenticationError = GitlabAuthenticationErrorStub
    gitlab_exceptions_module.GitlabGetError = GitlabGetErrorStub
    gitlab_exceptions_module.GitlabCreateError = GitlabCreateErrorStub

    gitlab_stub.Gitlab = GitlabStub
    gitlab_stub.exceptions = gitlab_exceptions_module
    sys.modules["gitlab"] = gitlab_stub
    sys.modules["gitlab.exceptions"] = gitlab_exceptions_module


from app.services.issues import IssueSyncError, test_integration_connection


class FakeGithubException(Exception):
    def __init__(self, status=None, data=None, headers=None):
        self.status = status
        super().__init__(status)


def _install_fake_github(monkeypatch, github_class):
    module = types.ModuleType("github")

    module.Github = github_class
    module.GithubException = FakeGithubException
    monkeypatch.setitem(sys.modules, "github", module)
    monkeypatch.setitem(sys.modules, "github.GithubException", module)
    return FakeGithubException


def test_test_integration_success_github(monkeypatch):
    captured = {}

    class FakeUser:
        login = "tester"

    class FakeGithub:
        def __init__(self, token, base_url=None, timeout=None):
            captured["token"] = token
            captured["base_url"] = base_url
            captured["timeout"] = timeout

        def get_user(self):
            captured["called"] = True
            return FakeUser()

    _install_fake_github(monkeypatch, FakeGithub)

    message = test_integration_connection("github", "token-123", None)

    assert captured["token"] == "token-123"
    assert captured["base_url"] == "https://api.github.com"
    assert captured["called"] is True
    assert "verified" in message.lower()


def test_test_integration_success_gitlab(monkeypatch):
    captured = {}

    class FakeGitlab:
        def __init__(self, url, private_token=None, timeout=None):
            captured["url"] = url
            captured["token"] = private_token
            captured["timeout"] = timeout

        def auth(self):
            captured["auth"] = True

    monkeypatch.setattr(sys.modules["gitlab"], "Gitlab", FakeGitlab)

    message = test_integration_connection(
        "gitlab", "token-123", "https://gitlab.example"
    )

    assert captured["url"] == "https://gitlab.example"
    assert captured["token"] == "token-123"
    assert captured["auth"] is True
    assert "verified" in message.lower()


def test_test_integration_success_jira(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        captured["timeout"] = kwargs.get("timeout")
        captured["auth"] = kwargs.get("auth")

        class _Response:
            status_code = 200

            def raise_for_status(self):
                return None

        return _Response()

    monkeypatch.setattr("app.services.issues.utils.requests.get", fake_get)

    message = test_integration_connection(
        "jira",
        "token-123",
        "https://jira.example",
        username="user@example.com",
    )

    assert captured["url"] == "https://jira.example/rest/api/3/myself"
    assert captured["headers"]["Accept"] == "application/json"
    assert isinstance(captured["auth"], HTTPBasicAuth)
    assert captured["auth"].username == "user@example.com"
    assert captured["auth"].password == "token-123"
    assert captured["timeout"] is not None
    assert "verified" in message.lower()


def test_test_integration_unauthorized(monkeypatch):
    class FailingGithub:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_user(self):
            raise FakeGithubException(
                status=401, data={"message": "bad creds"}, headers={}
            )

    FakeGithubException = _install_fake_github(monkeypatch, FailingGithub)

    with pytest.raises(IssueSyncError) as exc:
        test_integration_connection("github", "invalid", None)

    assert "401" in str(exc.value)


def test_test_integration_unsupported_provider():
    with pytest.raises(IssueSyncError) as exc:
        test_integration_connection("unknown", "token", None)

    assert "Unsupported issue provider" in str(exc.value)


def test_test_integration_requires_jira_username():
    with pytest.raises(IssueSyncError) as exc:
        test_integration_connection("jira", "token-123", "https://jira.example")

    assert "account email" in str(exc.value)
