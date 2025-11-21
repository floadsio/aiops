"""Tests for issue remapping functionality."""
from __future__ import annotations

import pytest

from app import create_app, db
from app.config import Config
from app.models import (
    ExternalIssue,
    TenantIntegration,
    Project,
    ProjectIntegration,
    Tenant,
    User,
)
from app.security import hash_password


@pytest.fixture
def test_app(tmp_path):
    """Create test application with database."""
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'remap.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    instance_dir = tmp_path / "instance"
    app = create_app(TestConfig, instance_path=instance_dir)

    with app.app_context():
        db.create_all()

        # Create admin user
        admin = User(
            email="admin@example.com",
            name="Admin User",
            password_hash=hash_password("password123"),
            is_admin=True,
        )
        db.session.add(admin)

        # Create tenant
        tenant = Tenant(name="Test Tenant", description="Test tenant")
        db.session.add(tenant)
        db.session.flush()

        # Create projects
        project_a = Project(
            name="Project A",
            repo_url="https://github.com/test/project-a",
            default_branch="main",
            tenant_id=tenant.id,
            owner_id=admin.id,
            local_path="/tmp/project-a",
        )
        project_b = Project(
            name="Project B",
            repo_url="https://github.com/test/project-b",
            default_branch="main",
            tenant_id=tenant.id,
            owner_id=admin.id,
            local_path="/tmp/project-b",
        )
        db.session.add_all([project_a, project_b])
        db.session.flush()

        # Create integration
        integration = TenantIntegration(
            name="GitHub Test",
            provider="github",
            tenant_id=tenant.id,
            api_token="dummy_token",
        )
        db.session.add(integration)
        db.session.flush()

        # Create project integrations
        pi_a = ProjectIntegration(
            project_id=project_a.id,
            integration_id=integration.id,
            external_identifier="test/project-a",
        )
        pi_b = ProjectIntegration(
            project_id=project_b.id,
            integration_id=integration.id,
            external_identifier="test/project-b",
        )
        db.session.add_all([pi_a, pi_b])
        db.session.flush()

        # Create test issue in Project A
        issue = ExternalIssue(
            project_integration_id=pi_a.id,
            external_id="123",
            title="Test Issue",
            status="open",
            assignee="Test User",
            url="https://github.com/test/project-a/issues/123",
            labels=["bug", "feature"],
            comments=[],
        )
        db.session.add(issue)
        db.session.commit()

    yield app


def login(client):
    """Log in as admin user."""
    return client.post(
        "/login",
        data={"email": "admin@example.com", "password": "password123"},
        follow_redirects=True,
    )


def test_remap_issue_success(test_app):
    """Test successfully remapping an issue to a different project."""
    client = test_app.test_client()
    login(client)

    with test_app.app_context():
        # Get the issue and projects
        issue = ExternalIssue.query.first()
        project_a = Project.query.filter_by(name="Project A").first()
        project_b = Project.query.filter_by(name="Project B").first()

        assert issue is not None
        assert project_a is not None
        assert project_b is not None

        # Verify issue is initially in Project A
        assert issue.project_integration.project_id == project_a.id

        # Remap to Project B
        response = client.post(
            f"/api/v1/issues/{issue.id}/remap",
            json={"project_id": project_b.id},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["issue"]["project_name"] == "Project B"

        # Verify issue is now in Project B
        db.session.refresh(issue)
        assert issue.project_integration.project_id == project_b.id


def test_remap_issue_same_project(test_app):
    """Test remapping an issue to the same project fails."""
    client = test_app.test_client()
    login(client)

    with test_app.app_context():
        issue = ExternalIssue.query.first()
        project_a = Project.query.filter_by(name="Project A").first()

        assert issue is not None
        assert project_a is not None

        # Try to remap to the same project
        response = client.post(
            f"/api/v1/issues/{issue.id}/remap",
            json={"project_id": project_a.id},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "already in the target project" in data["error"].lower()


def test_remap_issue_invalid_project(test_app):
    """Test remapping an issue to a non-existent project fails."""
    client = test_app.test_client()
    login(client)

    with test_app.app_context():
        issue = ExternalIssue.query.first()

        assert issue is not None

        # Try to remap to non-existent project
        response = client.post(
            f"/api/v1/issues/{issue.id}/remap",
            json={"project_id": 99999},
        )

        assert response.status_code == 404
        data = response.get_json()
        assert "not found" in data["error"].lower()


def test_remap_issue_missing_project_id(test_app):
    """Test remapping without providing project_id fails."""
    client = test_app.test_client()
    login(client)

    with test_app.app_context():
        issue = ExternalIssue.query.first()

        assert issue is not None

        # Try to remap without project_id
        response = client.post(
            f"/api/v1/issues/{issue.id}/remap",
            json={},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "project_id" in data["error"].lower()


def test_remap_issue_creates_project_integration(test_app):
    """Test that remapping creates ProjectIntegration if it doesn't exist."""
    client = test_app.test_client()
    login(client)

    with test_app.app_context():
        # Create a new project without a project integration for the same integration
        tenant = Tenant.query.first()
        admin = User.query.filter_by(email="admin@example.com").first()
        project_c = Project(
            name="Project C",
            repo_url="https://github.com/test/project-c",
            default_branch="main",
            tenant_id=tenant.id,
            owner_id=admin.id,
            local_path="/tmp/project-c",
        )
        db.session.add(project_c)
        db.session.commit()

        issue = ExternalIssue.query.first()
        assert issue is not None

        # Verify ProjectIntegration doesn't exist for Project C
        integration_id = issue.project_integration.integration_id
        pi_c = ProjectIntegration.query.filter_by(
            project_id=project_c.id,
            integration_id=integration_id
        ).first()
        assert pi_c is None

        # Remap to Project C
        response = client.post(
            f"/api/v1/issues/{issue.id}/remap",
            json={"project_id": project_c.id},
        )

        assert response.status_code == 200

        # Verify ProjectIntegration was created
        pi_c = ProjectIntegration.query.filter_by(
            project_id=project_c.id,
            integration_id=integration_id
        ).first()
        assert pi_c is not None

        # Verify issue uses the new ProjectIntegration
        db.session.refresh(issue)
        assert issue.project_integration_id == pi_c.id
