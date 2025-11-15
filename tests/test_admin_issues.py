from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from app.services.agent_context import MISSING_ISSUE_DETAILS_MESSAGE


class AdminTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(tmp_path):
    class _Config(AdminTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'issues.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    application = create_app(_Config)
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    with application.app_context():
        db.create_all()

        user = User(
            email="admin@example.com",
            name="Admin",
            password_hash=hash_password("password123"),
            is_admin=True,
        )
        tenant = Tenant(name="tenant-one", description="Tenant One")
        db.session.add_all([user, tenant])
        db.session.commit()

        project = Project(
            name="demo-project",
            repo_url="https://example.com/demo.git",
            default_branch="main",
            local_path=str(repos_dir / "demo-project"),
            description="Demo project",
            tenant_id=tenant.id,
            owner_id=user.id,
        )
        integration = TenantIntegration(
            tenant_id=tenant.id,
            provider="jira",
            name="Jira Cloud",
            base_url="https://example.atlassian.net",
            api_token="secret",
            enabled=True,
            settings={"username": "jira@example.com"},
        )
        db.session.add_all([project, integration])
        db.session.commit()

        project_integration = ProjectIntegration(
            project_id=project.id,
            integration_id=integration.id,
            external_identifier="demo::repo",
            config={},
        )
        db.session.add(project_integration)
        db.session.commit()

        now = datetime.now(timezone.utc)
        issues = [
            ExternalIssue(
                project_integration_id=project_integration.id,
                external_id="ISSUE-001",
                title="Delta outage",
                status="Open",
                assignee="sam@example.com",
                labels=["incident"],
                external_updated_at=now - timedelta(hours=2),
                raw_payload={
                    "fields": {
                        "description": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Enable InnoDB page tracking for faster incremental backups.",
                                        }
                                    ],
                                },
                                {
                                    "type": "bulletList",
                                    "content": [
                                        {
                                            "type": "listItem",
                                            "content": [
                                                {
                                                    "type": "paragraph",
                                                    "content": [
                                                        {
                                                            "type": "text",
                                                            "text": "Set innodb_page_tracking=ON in my.cnf",
                                                        }
                                                    ],
                                                }
                                            ],
                                        },
                                        {
                                            "type": "listItem",
                                            "content": [
                                                {
                                                    "type": "paragraph",
                                                    "content": [
                                                        {
                                                            "type": "text",
                                                            "text": "Schedule incremental xtrabackup run",
                                                        }
                                                    ],
                                                }
                                            ],
                                        },
                                    ],
                                },
                            ],
                        }
                    }
                },
                comments=[
                    {
                        "author": "sam@example.com",
                        "body": "Please attach the latest slow query logs.",
                        "created_at": "2024-01-01T12:00:00+00:00",
                        "url": "https://example.atlassian.net/browse/ISSUE-001?focusedCommentId=1",
                    }
                ],
            ),
            ExternalIssue(
                project_integration_id=project_integration.id,
                external_id="ISSUE-002",
                title="alpha follow-up",
                status="Open",
                assignee=None,
                labels=["follow-up"],
                external_updated_at=now - timedelta(hours=1),
            ),
            ExternalIssue(
                project_integration_id=project_integration.id,
                external_id="ISSUE-003",
                title="Bravo fix",
                status="Open",
                assignee=None,
                labels=["bug", "priority"],
                external_updated_at=now - timedelta(days=1),
            ),
        ]
        db.session.add_all(issues)
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login_admin(client):
    response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "password123"},
        follow_redirects=True,
    )
    assert response.status_code == 200


def _positions_in_html(html: str, identifiers: list[str]) -> list[int]:
    positions: list[int] = []
    cursor = 0
    for identifier in identifiers:
        index = html.index(identifier, cursor)
        positions.append(index)
        cursor = index + len(identifier)
    return positions


def _add_project_with_issue(app, slug: str, *, external_id: str, title: str):
    repo_root = Path(app.config["REPO_STORAGE_PATH"])
    repo_root.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").one()
        tenant = Tenant.query.first()
        integration = TenantIntegration.query.first()

        project = Project(
            name=f"{slug}-project",
            repo_url=f"https://example.com/{slug}.git",
            default_branch="main",
            local_path=str(repo_root / slug),
            description=f"{slug.title()} project",
            tenant_id=tenant.id,
            owner_id=user.id,
        )
        db.session.add(project)
        db.session.commit()

        link = ProjectIntegration(
            project_id=project.id,
            integration_id=integration.id,
            external_identifier=f"{slug}::repo",
            config={},
        )
        db.session.add(link)
        db.session.commit()

        issue = ExternalIssue(
            project_integration_id=link.id,
            external_id=external_id,
            title=title,
            status="Open",
            external_updated_at=datetime.now(timezone.utc),
        )
        db.session.add(issue)
        db.session.commit()

        return project.id, issue.external_id, issue.title


def test_default_sorting_uses_updated_desc(client, login_admin):
    response = client.get("/admin/issues")
    assert response.status_code == 200

    body = response.get_data(as_text=True)
    order = _positions_in_html(body, ["ISSUE-002", "ISSUE-001", "ISSUE-003"])

    assert order == sorted(order)


def test_can_sort_by_title_and_direction(client, login_admin):
    ascending = client.get("/admin/issues?sort=title&direction=asc")
    assert ascending.status_code == 200
    ascending_body = ascending.get_data(as_text=True)
    ascending_order = _positions_in_html(
        ascending_body,
        ["ISSUE-002", "ISSUE-003", "ISSUE-001"],
    )
    assert ascending_order == sorted(ascending_order)

    descending = client.get("/admin/issues?sort=title&direction=desc")
    assert descending.status_code == 200
    descending_body = descending.get_data(as_text=True)
    descending_order = _positions_in_html(
        descending_body,
        ["ISSUE-001", "ISSUE-003", "ISSUE-002"],
    )
    assert descending_order == sorted(descending_order)


def test_invalid_sort_falls_back_to_default(client, login_admin):
    response = client.get("/admin/issues?sort=unknown&direction=desc")
    assert response.status_code == 200

    body = response.get_data(as_text=True)
    order = _positions_in_html(body, ["ISSUE-002", "ISSUE-001", "ISSUE-003"])
    assert order == sorted(order)


def test_issue_detail_row_includes_description(client, login_admin):
    response = client.get("/admin/issues")
    assert response.status_code == 200

    body = response.get_data(as_text=True)
    assert "Enable InnoDB page tracking for faster incremental backups." in body
    assert MISSING_ISSUE_DETAILS_MESSAGE in body
    assert "issue-status-select" in body
    assert "Custom status…" in body


def test_issue_comments_rendered(client, login_admin):
    response = client.get("/admin/issues")
    assert response.status_code == 200

    body = response.get_data(as_text=True)
    assert "Please attach the latest slow query logs." in body


def test_project_filter_dropdown_present(client, login_admin):
    response = client.get("/admin/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="project"' in body
    assert "All projects" in body


def test_project_filter_limits_issues(client, login_admin, app):
    project_id, _, new_title = _add_project_with_issue(
        app,
        "omega",
        external_id="ISSUE-900",
        title="Omega fix",
    )

    response = client.get(f"/admin/issues?project={project_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert new_title in body
    assert "Delta outage" not in body


def test_api_issues_can_filter_by_project(client, login_admin, app):
    project_id, external_id, _ = _add_project_with_issue(
        app,
        "sigma",
        external_id="ISSUE-901",
        title="Sigma follow-up",
    )

    response = client.get(f"/api/issues?project_id={project_id}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["count"] == 1
    assert data["issues"][0]["external_id"] == external_id
    assert data["issues"][0]["project_id"] == project_id


def test_admin_can_update_issue_status(client, login_admin, app):
    with app.app_context():
        issue = ExternalIssue.query.filter_by(external_id="ISSUE-001").one()
        issue_id = issue.id

    response = client.post(
        f"/admin/issues/{issue_id}/status",
        data={"status": "In Progress", "next": "/admin/issues"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        updated = ExternalIssue.query.get(issue_id)
        assert updated.status == "In Progress"


def test_admin_can_clear_issue_status(client, login_admin, app):
    with app.app_context():
        issue = ExternalIssue.query.filter_by(external_id="ISSUE-002").one()
        issue_id = issue.id

    response = client.post(
        f"/admin/issues/{issue_id}/status",
        data={"status": "", "next": "/admin/issues"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        updated = ExternalIssue.query.get(issue_id)
        assert updated.status is None


def test_force_full_refresh_triggers_full_sync(client, login_admin, monkeypatch):
    calls = {}

    def fake_sync(integrations, *, force_full=False):
        calls["force_full"] = force_full
        return {integration.id: [] for integration in integrations}

    monkeypatch.setattr("app.routes.admin.sync_tenant_integrations", fake_sync)

    response = client.post(
        "/admin/issues/refresh",
        data={"force_full": "1"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Completed full issue resync" in body
    assert calls.get("force_full") is True
