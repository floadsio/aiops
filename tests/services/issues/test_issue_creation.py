from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import create_app, db
from app.config import Config
from app.models import Project, ProjectIntegration, Tenant, TenantIntegration, User
from app.security import hash_password
from app.services import issues
from app.services.issues import IssuePayload, IssueSyncError


class IssueCreationConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


def _init_app(tmp_path: Path):
    class _Config(IssueCreationConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'issues-create.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    return create_app(_Config)


def _seed_project(tmp_path: Path, provider: str = "jira"):
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
    settings = {}
    if provider == "jira":
        settings["username"] = "user@example.com"
    integration = TenantIntegration(
        tenant=tenant,
        provider=provider,
        name="Integration",
        api_token="token-123",
        enabled=True,
        settings=settings,
    )
    project_integration = ProjectIntegration(
        project=project,
        integration=integration,
        external_identifier="DEVOPS",
        config={},
    )
    return user, tenant, project, integration, project_integration


def test_create_issue_for_project_integration(tmp_path, monkeypatch):
    app = _init_app(tmp_path)
    with app.app_context():
        db.create_all()
        user, tenant, project, integration, project_integration = _seed_project(tmp_path)
        db.session.add_all([user, tenant, project, integration, project_integration])
        db.session.commit()

        captured = {}

        def fake_creator(integration_obj, project_integration_obj, request):
            captured["integration"] = integration_obj
            captured["project_integration"] = project_integration_obj
            captured["request"] = request
            return IssuePayload(
                external_id="DEVOPS-100",
                title=request.summary,
                status="To Do",
                assignee=None,
                url="https://example.atlassian.net/browse/DEVOPS-100",
                labels=request.labels or [],
                external_updated_at=datetime(2024, 10, 1, tzinfo=timezone.utc),
                raw={"key": "DEVOPS-100"},
            )

        monkeypatch.setitem(issues.CREATE_PROVIDER_REGISTRY, "jira", fake_creator)

        payload = issues.create_issue_for_project_integration(
            project_integration,
            summary="Provision new environment",
            description="Create infra",
            issue_type="Task",
            labels=["infra"],
        )

        assert payload.external_id == "DEVOPS-100"
        assert captured["request"].summary == "Provision new environment"
        assert captured["request"].description == "Create infra"
        assert captured["request"].issue_type == "Task"
        assert captured["request"].labels == ["infra"]


def test_create_issue_for_project_integration_unsupported(tmp_path):
    app = _init_app(tmp_path)
    with app.app_context():
        db.create_all()
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
            tenant=tenant,
            owner=user,
            local_path=str(tmp_path / "repos" / "demo"),
        )
        integration = TenantIntegration(
            tenant=tenant,
            provider="bitbucket",
            name="Unsupported",
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
        db.session.add_all([user, tenant, project, integration, project_integration])
        db.session.commit()

        with pytest.raises(IssueSyncError):
            issues.create_issue_for_project_integration(
                project_integration,
                summary="Will fail",
            )
