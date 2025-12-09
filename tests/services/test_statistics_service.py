"""Tests for the statistics service."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.statistics_service import (
    get_contributor_statistics,
    get_project_list,
    get_resolution_statistics,
    get_workflow_statistics,
)


@pytest.fixture
def mock_db_session(monkeypatch):
    """Mock database session."""
    queries = {}

    class MockQuery:
        def __init__(self, model_name):
            self.model_name = model_name
            self._filters = []
            self._joins = []
            self._options = []

        def filter(self, *args):
            self._filters.extend(args)
            return self

        def join(self, *args):
            self._joins.extend(args)
            return self

        def options(self, *args):
            self._options.extend(args)
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return queries.get(self.model_name, [])

        def first(self):
            results = self.all()
            return results[0] if results else None

    class MockSession:
        def query(self, model):
            model_name = model.__name__ if hasattr(model, "__name__") else str(model)
            return MockQuery(model_name)

    mock_session = MockSession()
    queries["_session"] = mock_session
    return queries


def test_get_resolution_statistics_empty(mock_db_session, monkeypatch):
    """Test resolution statistics with no issues."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])
    mock_db_session["ExternalIssue"] = []

    stats = get_resolution_statistics(days=30)

    assert stats["total_resolved"] == 0
    assert stats["avg_resolution_time_hours"] == 0
    assert stats["project_breakdown"] == {}
    assert stats["period_days"] == 30


def test_get_resolution_statistics_with_issues(mock_db_session, monkeypatch):
    """Test resolution statistics with resolved issues."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])

    # Create mock issues
    now = datetime.utcnow()
    project_mock = SimpleNamespace(name="Test Project", tenant=SimpleNamespace(name="Test Tenant"))
    project_integration_mock = SimpleNamespace(project=project_mock)

    issues = [
        SimpleNamespace(
            id=1,
            external_id="1",
            title="Issue 1",
            status="closed",
            created_at=now - timedelta(hours=24),
            updated_at=now,
            project_integration=project_integration_mock,
        ),
        SimpleNamespace(
            id=2,
            external_id="2",
            title="Issue 2",
            status="resolved",
            created_at=now - timedelta(hours=48),
            updated_at=now,
            project_integration=project_integration_mock,
        ),
    ]

    mock_db_session["ExternalIssue"] = issues

    stats = get_resolution_statistics(days=30)

    assert stats["total_resolved"] == 2
    assert stats["avg_resolution_time_hours"] == 36.0  # (24 + 48) / 2
    assert "Test Project" in stats["project_breakdown"]
    assert stats["project_breakdown"]["Test Project"]["count"] == 2


def test_get_workflow_statistics_empty(mock_db_session, monkeypatch):
    """Test workflow statistics with no issues."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])
    mock_db_session["ExternalIssue"] = []

    stats = get_workflow_statistics()

    assert stats["total_issues"] == 0
    assert stats["open_count"] == 0
    assert stats["closed_count"] == 0
    assert stats["status_distribution"] == {}


def test_get_workflow_statistics_with_issues(mock_db_session, monkeypatch):
    """Test workflow statistics with various issue statuses."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])

    project_mock = SimpleNamespace(name="Test Project", tenant=SimpleNamespace(name="Test Tenant"))
    project_integration_mock = SimpleNamespace(project=project_mock)

    issues = [
        SimpleNamespace(
            id=1, status="open", project_integration=project_integration_mock
        ),
        SimpleNamespace(
            id=2, status="open", project_integration=project_integration_mock
        ),
        SimpleNamespace(
            id=3, status="closed", project_integration=project_integration_mock
        ),
        SimpleNamespace(
            id=4, status="in_progress", project_integration=project_integration_mock
        ),
    ]

    mock_db_session["ExternalIssue"] = issues

    stats = get_workflow_statistics()

    assert stats["total_issues"] == 4
    assert stats["open_count"] == 3  # open + in_progress
    assert stats["closed_count"] == 1
    assert stats["status_distribution"]["Open"] == 2
    assert stats["status_distribution"]["Closed"] == 1
    assert stats["status_distribution"]["In Progress"] == 1


def test_get_contributor_statistics_empty(mock_db_session, monkeypatch):
    """Test contributor statistics with no issues."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])
    mock_db_session["ExternalIssue"] = []

    stats = get_contributor_statistics(days=30)

    assert stats == []


def test_get_contributor_statistics_with_activity(mock_db_session, monkeypatch):
    """Test contributor statistics with assigned issues and comments."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])

    now = datetime.utcnow()
    project_mock = SimpleNamespace(name="Test Project", tenant=SimpleNamespace(name="Test Tenant"))
    project_integration_mock = SimpleNamespace(project=project_mock)

    issues = [
        SimpleNamespace(
            id=1,
            external_id="1",
            title="Issue 1",
            status="open",
            assignee="user1@example.com",
            url="https://example.com/issue/1",
            comments=[{"author": "user1@example.com", "body": "Comment 1"}],
            updated_at=now,
            project_integration=project_integration_mock,
        ),
        SimpleNamespace(
            id=2,
            external_id="2",
            title="Issue 2",
            status="closed",
            assignee="user2@example.com",
            url="https://example.com/issue/2",
            comments=[
                {"author": "user1@example.com", "body": "Comment 2"},
                {"author": "user2@example.com", "body": "Comment 3"},
            ],
            updated_at=now,
            project_integration=project_integration_mock,
        ),
    ]

    mock_db_session["ExternalIssue"] = issues

    stats = get_contributor_statistics(days=30)

    # user1 has 1 assigned + 2 comments = 3 total activity
    # user2 has 1 assigned + 1 comment = 2 total activity
    assert len(stats) == 2
    assert stats[0]["contributor"] == "user1@example.com"
    assert stats[0]["total_activity"] == 3
    assert stats[1]["contributor"] == "user2@example.com"
    assert stats[1]["total_activity"] == 2


def test_get_project_list_empty(mock_db_session, monkeypatch):
    """Test project list with no projects."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])
    mock_db_session["Project"] = []

    projects = get_project_list()

    assert projects == []


def test_get_project_list_with_projects(mock_db_session, monkeypatch):
    """Test project list with multiple projects."""
    from app import services

    monkeypatch.setattr(services.statistics_service.db, "session", mock_db_session["_session"])

    projects = [
        SimpleNamespace(
            id=1,
            name="Project A",
            tenant=SimpleNamespace(name="Tenant 1"),
        ),
        SimpleNamespace(
            id=2,
            name="Project B",
            tenant=SimpleNamespace(name="Tenant 1"),
        ),
    ]

    mock_db_session["Project"] = projects

    result = get_project_list()

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[0]["name"] == "Project A"
    assert result[0]["tenant_name"] == "Tenant 1"
    assert result[1]["id"] == 2
    assert result[1]["name"] == "Project B"
