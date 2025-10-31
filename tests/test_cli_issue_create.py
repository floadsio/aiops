from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app import create_app, db
from app.config import Config
from app.models import Project, ProjectIntegration, Tenant, TenantIntegration, User
from app.security import hash_password
from app.services.issues import IssuePayload


class CliIssueConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


def _init_app(tmp_path: Path):
    class _Config(CliIssueConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'cli-issues.db'}"
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
        provider="jira",
        name="Jira Cloud",
        api_token="token-123",
        enabled=True,
        settings={"username": "user@example.com"},
    )
    project_integration = ProjectIntegration(
        project=project,
        integration=integration,
        external_identifier="DEVOPS",
        config={},
    )
    return user, tenant, project, integration, project_integration


def test_create_issue_command(tmp_path, monkeypatch):
    app = _init_app(tmp_path)
    with app.app_context():
        db.create_all()
        user, tenant, project, integration, project_integration = _seed_project(tmp_path)
        db.session.add_all([user, tenant, project, integration, project_integration])
        db.session.commit()
        project_integration_id = project_integration.id

    captured = {}

    def fake_create_issue(pi, **kwargs):
        captured["project_integration"] = pi
        captured["kwargs"] = kwargs
        return IssuePayload(
            external_id="DEVOPS-200",
            title=kwargs["summary"],
            status="To Do",
            assignee=None,
            url="https://example.atlassian.net/browse/DEVOPS-200",
            labels=kwargs.get("labels") or [],
            external_updated_at=datetime(2024, 10, 1, tzinfo=timezone.utc),
            raw={"key": "DEVOPS-200"},
        )

    monkeypatch.setattr("app.cli.create_issue_for_project_integration", fake_create_issue)

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=[
            "create-issue",
            "--project-integration-id",
            str(project_integration_id),
            "--summary",
            "Add SLO dashboard",
            "--description",
            "Track core services.",
            "--issue-type",
            "Task",
            "--label",
            "observability",
            "--label",
            "priority-2",
        ]
    )

    assert result.exit_code == 0, result.output
    assert "created issue DEVOPS-200" in result.output
    assert "Issue URL" in result.output
    assert captured["project_integration"].id == project_integration_id
    assert captured["kwargs"]["summary"] == "Add SLO dashboard"
    assert captured["kwargs"]["description"] == "Track core services."
    assert captured["kwargs"]["issue_type"] == "Task"
    assert captured["kwargs"]["labels"] == ["observability", "priority-2"]


def test_create_issue_command_missing_integration(tmp_path):
    app = _init_app(tmp_path)
    with app.app_context():
        db.create_all()

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=[
            "create-issue",
            "--project-integration-id",
            "999",
            "--summary",
            "Will fail",
        ]
    )
    assert result.exit_code != 0
    assert "Project integration not found" in result.output
