from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

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
    PROVIDER_REGISTRY,
    IssueCommentPayload,
    IssuePayload,
    sync_project_integration,
)


class IssueTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


def _init_app(tmp_path: Path):
    class _Config(IssueTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'issues.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    return create_app(_Config)


def _seed_project(tmp_path: Path):
    user = User(
        email="owner@example.com",
        name="Owner",
        password_hash=hash_password("secret123"),
        is_admin=True,
    )
    tenant = Tenant(name="tenant-a", description="Tenant A")
    project = Project(
        name="demo",
        repo_url="git@example.com/demo.git",
        default_branch="main",
        description="Demo project",
        tenant=tenant,
        owner=user,
        local_path=str(tmp_path / "repos" / "demo"),
    )
    integration = TenantIntegration(
        tenant=tenant,
        provider="gitlab",
        name="GitLab Cloud",
        api_token="token-123",
        enabled=True,
        settings={},
    )
    project_integration = ProjectIntegration(
        project=project,
        integration=integration,
        external_identifier="group/demo",
        config={},
    )
    return user, tenant, project, integration, project_integration


def test_sync_project_integration_creates_and_updates(tmp_path, monkeypatch):
    app = _init_app(tmp_path)
    with app.app_context():
        db.create_all()
        user, tenant, project, integration, project_integration = _seed_project(
            tmp_path
        )
        db.session.add_all([user, tenant, project, integration, project_integration])
        db.session.commit()

        first_payload = IssuePayload(
            external_id="123",
            title="First issue",
            status="opened",
            assignee="alice",
            url="https://gitlab.example/issues/123",
            labels=["bug", "urgent"],
            external_updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            raw={"id": 123},
            comments=[
                IssueCommentPayload(
                    author="alice",
                    body="Initial context.",
                    created_at=datetime(2024, 1, 1, 10, tzinfo=timezone.utc),
                    url="https://gitlab.example/issues/123#note_1",
                )
            ],
        )

        second_payload = IssuePayload(
            external_id="123",
            title="First issue (updated)",
            status="closed",
            assignee="bob",
            url="https://gitlab.example/issues/123",
            labels=["bug"],
            external_updated_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            raw={"id": 123, "state": "closed"},
            comments=[
                IssueCommentPayload(
                    author="bob",
                    body="Fixed in main.",
                    created_at=datetime(2024, 1, 2, 9, tzinfo=timezone.utc),
                    url="https://gitlab.example/issues/123#note_2",
                )
            ],
        )

        monkeypatch.setitem(PROVIDER_REGISTRY, "gitlab", lambda *_: [first_payload])
        sync_project_integration(project_integration)

        issue = ExternalIssue.query.filter_by(external_id="123").one()
        assert issue.title == "First issue"
        assert issue.status == "opened"
        assert issue.assignee == "alice"
        assert issue.last_seen_at is not None
        assert project_integration.last_synced_at is not None
        assert issue.comments == [
            {
                "author": "alice",
                "body": "Initial context.",
                "url": "https://gitlab.example/issues/123#note_1",
                "created_at": "2024-01-01T10:00:00+00:00",
            }
        ]

        monkeypatch.setitem(PROVIDER_REGISTRY, "gitlab", lambda *_: [second_payload])
        sync_project_integration(project_integration)

        issue = ExternalIssue.query.filter_by(external_id="123").one()
        assert issue.title == "First issue (updated)"
        assert issue.status == "closed"
        assert issue.assignee == "bob"
        assert issue.labels == ["bug"]
        assert issue.external_updated_at == datetime(2024, 1, 2, tzinfo=timezone.utc)
        assert issue.comments == [
            {
                "author": "bob",
                "body": "Fixed in main.",
                "url": "https://gitlab.example/issues/123#note_2",
                "created_at": "2024-01-02T09:00:00+00:00",
            }
        ]


def test_sync_issues_command_invokes_service(tmp_path, monkeypatch):
    app = _init_app(tmp_path)
    with app.app_context():
        db.create_all()
        user, tenant, project, integration, project_integration = _seed_project(
            tmp_path
        )
        db.session.add_all([user, tenant, project, integration, project_integration])
        db.session.commit()
        project_integration_id = project_integration.id

    captured: Dict[str, List[int]] = {}

    def fake_sync(integrations, *, force_full=False):
        captured["ids"] = [pi.id for pi in integrations]
        return {pi.id: [object()] for pi in integrations}

    monkeypatch.setattr("app.cli.sync_tenant_integrations", fake_sync)

    runner = app.test_cli_runner()
    result = runner.invoke(args=["sync-issues"])
    assert result.exit_code == 0, result.output
    assert captured["ids"] == [project_integration_id]
    assert "[gitlab]" in result.output
    assert "Issue synchronization completed." in result.output
