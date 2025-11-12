from __future__ import annotations

import pytest

from app import create_app, db
from app.config import Config
from app.models import (
    ExternalIssue,
    Project,
    ProjectIntegration,
    Tenant,
    TenantIntegration,
    User,
)
from app.security import hash_password
from app.services.issues import (
    ISSUE_STATUS_MAX_LENGTH,
    IssueUpdateError,
    update_issue_status,
)


class IssueStatusTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(tmp_path):
    class _Config(IssueStatusTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'issues.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    application = create_app(_Config)

    with application.app_context():
        db.create_all()

        user = User(
            email="status-admin@example.com",
            name="Status Admin",
            password_hash=hash_password("changeme123"),
            is_admin=True,
        )
        tenant = Tenant(name="status-tenant", description="Tenant for status tests")
        project = Project(
            name="status-project",
            repo_url="https://example.com/status.git",
            default_branch="main",
            description="Status project",
            tenant=tenant,
            owner=user,
            local_path=str(tmp_path / "repos" / "status-project"),
        )
        integration = TenantIntegration(
            tenant=tenant,
            provider="jira",
            name="Jira Cloud",
            api_token="token",
            enabled=True,
            settings={},
        )
        project_integration = ProjectIntegration(
            project=project,
            integration=integration,
            external_identifier="STATUS",
            config={},
        )
        issue = ExternalIssue(
            project_integration=project_integration,
            external_id="STATUS-1",
            title="Initial issue",
            status="Open",
        )
        db.session.add_all(
            [user, tenant, project, integration, project_integration, issue]
        )
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _get_issue():
    return ExternalIssue.query.filter_by(external_id="STATUS-1").one()


def test_update_issue_status_trims_and_sets_value(app):
    with app.app_context():
        issue = _get_issue()
        update_issue_status(issue.id, "  In Progress  ")
        db.session.commit()

        refreshed = _get_issue()
        assert refreshed.status == "In Progress"


def test_update_issue_status_allows_clearing(app):
    with app.app_context():
        issue = _get_issue()
        update_issue_status(issue.id, "   ")
        db.session.commit()

        refreshed = _get_issue()
        assert refreshed.status is None


def test_update_issue_status_enforces_length(app):
    with app.app_context():
        issue = _get_issue()
        too_long = "A" * (ISSUE_STATUS_MAX_LENGTH + 1)
        with pytest.raises(IssueUpdateError):
            update_issue_status(issue.id, too_long)
        db.session.rollback()

        refreshed = _get_issue()
        assert refreshed.status == issue.status


def test_update_issue_status_missing_issue(app):
    with app.app_context():
        with pytest.raises(IssueUpdateError):
            update_issue_status(9999, "Closed")
