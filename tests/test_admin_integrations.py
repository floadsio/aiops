from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import create_app, db
from app.config import Config
from app.models import Project, ProjectIntegration, SSHKey, Tenant, TenantIntegration, User
from app.security import hash_password
from app.services.key_service import resolve_private_key_path
from app.services.update_service import UpdateError


class AdminTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(tmp_path):
    class _Config(AdminTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'admin.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    application = create_app(_Config)
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
    yield application


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


def test_can_create_tenant_integration(app, client, login_admin):
    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        assert tenant is not None
        tenant_id = tenant.id

    response = client.post(
        "/admin/integrations",
        data={
            "tenant_id": tenant_id,
            "name": "GitLab Cloud",
            "provider": "gitlab",
            "base_url": "",
            "api_token": "secret-token",
            "enabled": "y",
            "save": "Save Integration",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        integration = TenantIntegration.query.filter_by(name="GitLab Cloud").first()
        assert integration is not None
        assert integration.provider == "gitlab"
        assert integration.tenant_id == tenant_id
        assert integration.api_token == "secret-token"


def test_jira_integration_requires_email(app, client, login_admin):
    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        assert tenant is not None
        tenant_id = tenant.id

    response_missing_email = client.post(
        "/admin/integrations",
        data={
            "tenant_id": tenant_id,
            "name": "Jira Cloud",
            "provider": "jira",
            "base_url": "https://example.atlassian.net",
            "api_token": "secret-token",
            "enabled": "y",
            "save": "Save Integration",
        },
        follow_redirects=True,
    )
    assert response_missing_email.status_code == 200

    with app.app_context():
        assert TenantIntegration.query.filter_by(name="Jira Cloud").count() == 0

    response_with_email = client.post(
        "/admin/integrations",
        data={
            "tenant_id": tenant_id,
            "name": "Jira Cloud",
            "provider": "jira",
            "base_url": "https://example.atlassian.net",
            "api_token": "secret-token",
            "jira_email": "admin@example.com",
            "enabled": "y",
            "save": "Save Integration",
        },
        follow_redirects=True,
    )
    assert response_with_email.status_code == 200

    with app.app_context():
        integration = TenantIntegration.query.filter_by(name="Jira Cloud").first()
        assert integration is not None
        assert integration.settings.get("username") == "admin@example.com"


def test_test_integration_endpoint(app, client, login_admin, monkeypatch):
    captured = {}

    def fake_test_integration(provider, api_token, base_url, username=None):
        captured["args"] = (provider, api_token, base_url, username)
        return "Credentials verified."

    monkeypatch.setattr("app.routes.admin.test_integration_connection", fake_test_integration)

    response = client.post(
        "/admin/integrations/test",
        json={
            "provider": "gitlab",
            "api_token": "token-123",
            "base_url": "",
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert "verified" in data["message"]
    assert captured["args"] == ("gitlab", "token-123", None, None)


def test_can_update_and_delete_project_integration(app, client, login_admin):
    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        user = User.query.filter_by(email="admin@example.com").first()
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            tenant=tenant,
            owner=user,
            local_path="/tmp/demo",
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
        db.session.add_all([project, integration, project_integration])
        db.session.commit()
        link_id = project_integration.id

    update_resp = client.post(
        f"/admin/integrations/project/{link_id}/update",
        data={
            "external_identifier": "kumbe/devops/demo",
            "jira_jql": "",
            "submit": "Update Link",
        },
        follow_redirects=True,
    )
    assert update_resp.status_code == 200

    with app.app_context():
        link = ProjectIntegration.query.get(link_id)
        assert link.external_identifier == "kumbe/devops/demo"

    delete_resp = client.post(
        f"/admin/integrations/project/{link_id}/delete",
        data={"submit": "Remove Link"},
        follow_redirects=True,
    )
    assert delete_resp.status_code == 200

    with app.app_context():
        assert ProjectIntegration.query.get(link_id) is None


def test_admin_can_trigger_update(app, client, login_admin, monkeypatch):
    class DummyResult:
        def __init__(self):
            self.command = "/bin/bash scripts/update.sh"
            self.returncode = 0
            self.stdout = "update completed"
            self.stderr = ""

        @property
        def ok(self):
            return True

    calls = {}

    def fake_run_update():
        calls["invoked"] = True
        return DummyResult()

    monkeypatch.setattr("app.routes.admin.run_update_script", fake_run_update)

    restart_calls = {}

    def fake_trigger(command):
        restart_calls["command"] = command
        return True, "Restart scheduled"

    monkeypatch.setattr("app.routes.admin._trigger_restart", fake_trigger)

    response = client.post(
        "/admin/system/update",
        data={"restart": "y", "submit": "Run update script"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert calls.get("invoked") is True
    assert b"Update succeeded" in response.data
    assert b"update-log" in response.data
    assert restart_calls.get("command") is None
    assert b"Restart scheduled" in response.data


def test_admin_update_handles_error(app, client, login_admin, monkeypatch):
    def fake_run_update():
        raise UpdateError("script missing")

    monkeypatch.setattr("app.routes.admin.run_update_script", fake_run_update)

    response = client.post(
        "/admin/system/update",
        data={"submit": "Run update script"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"script missing" in response.data


def test_admin_update_restart_failure(app, client, login_admin, monkeypatch):
    class DummyResult:
        command = "/bin/bash scripts/update.sh"
        returncode = 0
        stdout = "done"
        stderr = ""

        @property
        def ok(self):
            return True

    monkeypatch.setattr("app.routes.admin.run_update_script", lambda: DummyResult())
    monkeypatch.setattr("app.routes.admin._trigger_restart", lambda cmd: (False, "Restart failed"))

    response = client.post(
        "/admin/system/update",
        data={"restart": "y", "submit": "Run update script"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Restart failed" in response.data


def test_can_delete_tenant(app, client, login_admin):
    with app.app_context():
        admin_user = User.query.filter_by(email="admin@example.com").first()
        removable_tenant = Tenant(name="removable", description="To be removed")
        project = Project(
            name="removable-project",
            repo_url="git@example.com/removable.git",
            default_branch="main",
            tenant=removable_tenant,
            owner=admin_user,
            local_path="/tmp/removable",
        )
        key = SSHKey(
            name="removable-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC",
            fingerprint="fingerprint-removable",
            user=admin_user,
            tenant=removable_tenant,
        )
        db.session.add_all([removable_tenant, project, key])
        db.session.commit()
        tenant_id = removable_tenant.id

    response = client.post(
        "/admin/tenants",
        data={"tenant_id": str(tenant_id), "submit": "Remove Tenant"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        assert Tenant.query.get(tenant_id) is None
        assert Project.query.filter_by(name="removable-project").count() == 0
        assert SSHKey.query.filter_by(fingerprint="fingerprint-removable").count() == 0


def test_can_delete_ssh_key(app, client, login_admin, tmp_path):
    with app.app_context():
        admin_user = User.query.filter_by(email="admin@example.com").first()
        private_key_path = tmp_path / "id_rsa"
        private_key_path.write_text("super-secret-private-key")
        ssh_key = SSHKey(
            name="admin-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7",
            fingerprint="fingerprint-admin-key",
            user=admin_user,
            tenant=None,
            private_key_path=str(private_key_path),
        )
        db.session.add(ssh_key)
        db.session.commit()
        key_id = ssh_key.id

    response = client.post(
        f"/admin/ssh-keys/{key_id}/delete",
        data={"key_id": str(key_id), "submit": "Remove Key"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        assert SSHKey.query.get(key_id) is None
    assert not private_key_path.exists()


def test_can_add_ssh_key_with_private_material(app, client, login_admin):
    private_key = """-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA-test-material\n-----END OPENSSH PRIVATE KEY-----\n"""

    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        assert tenant is not None
        tenant_id = tenant.id

    response = client.post(
        "/admin/ssh-keys",
        data={
            "name": "deploy",
            "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7",
            "tenant_id": str(tenant_id),
            "private_key": private_key,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        ssh_key = SSHKey.query.filter_by(name="deploy").first()
        assert ssh_key is not None
        assert ssh_key.private_key_path is not None
        stored_path = resolve_private_key_path(ssh_key.private_key_path)
        assert stored_path is not None
        assert stored_path.exists()
        assert stored_path.read_text().strip() == private_key.strip()
        assert (stored_path.stat().st_mode & 0o777) == 0o600


def test_can_update_and_remove_private_key(app, client, login_admin):
    new_private_key = """-----BEGIN OPENSSH PRIVATE KEY-----\nBBBB-test-material\n-----END OPENSSH PRIVATE KEY-----\n"""

    with app.app_context():
        admin_user = User.query.filter_by(email="admin@example.com").first()
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        assert admin_user is not None and tenant is not None
        tenant_id = tenant.id
        ssh_key = SSHKey(
            name="updatable",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC8",
            fingerprint="fingerprint-updatable",
            user=admin_user,
            tenant=tenant,
        )
        db.session.add(ssh_key)
        db.session.commit()
        key_id = ssh_key.id

    response_update = client.post(
        f"/admin/ssh-keys/{key_id}",
        data={
            "name": "updatable",
            "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC8",
            "tenant_id": str(tenant_id),
            "private_key": new_private_key,
        },
        follow_redirects=True,
    )
    assert response_update.status_code == 200

    with app.app_context():
        ssh_key = SSHKey.query.get(key_id)
        assert ssh_key is not None
        assert ssh_key.private_key_path is not None
        stored_path = resolve_private_key_path(ssh_key.private_key_path)
        assert stored_path is not None
        assert stored_path.exists()
        assert stored_path.read_text().strip() == new_private_key.strip()

    response_remove = client.post(
        f"/admin/ssh-keys/{key_id}",
        data={
            "name": "updatable",
            "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC8",
            "tenant_id": str(tenant_id),
            "private_key": "",
            "remove_private_key": "y",
        },
        follow_redirects=True,
    )
    assert response_remove.status_code == 200

    with app.app_context():
        ssh_key = SSHKey.query.get(key_id)
        assert ssh_key is not None
        assert ssh_key.private_key_path is None
    assert not stored_path.exists()


def test_dashboard_refresh_project_issues(app, client, login_admin, monkeypatch, tmp_path):
    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        user = User.query.filter_by(email="admin@example.com").first()
        project = Project(
            name="refreshable",
            repo_url="git@example.com/refreshable.git",
            default_branch="main",
            tenant=tenant,
            owner=user,
            local_path=str(tmp_path / "refreshable"),
        )
        integration = TenantIntegration(
            tenant=tenant,
            provider="jira",
            name="Jira Cloud",
            api_token="token-xyz",
            enabled=True,
            settings={"username": "user@example.com"},
        )
        project_integration = ProjectIntegration(
            project=project,
            integration=integration,
            external_identifier="DEVOPS",
            config={},
        )
        db.session.add_all([project, integration, project_integration])
        db.session.commit()
        link_id = project_integration.id
        project_id = project.id

    captured = {}

    def fake_sync(link):
        captured.setdefault("links", []).append(link.id)
        return [object()]

    monkeypatch.setattr("app.routes.admin.sync_project_integration", fake_sync)

    response = client.post(
        f"/admin/projects/{project_id}/refresh-issues",
        data={"project_id": str(project_id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert captured["links"] == [link_id]
    assert b"Refreshed issues for" in response.data or b"Issue cache for" in response.data


def test_dashboard_refresh_project_git(app, client, login_admin, monkeypatch, tmp_path):
    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        user = User.query.filter_by(email="admin@example.com").first()
        project = Project(
            name="git-refresh",
            repo_url="git@example.com/git-refresh.git",
            default_branch="main",
            tenant=tenant,
            owner=user,
            local_path=str(tmp_path / "git-refresh"),
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    captured = {}

    def fake_run(project_obj, action, ref=None, clean=False):
        captured["project"] = project_obj.id
        captured["action"] = action
        return "Pulled"

    monkeypatch.setattr("app.routes.admin.run_git_action", fake_run)

    response = client.post(
        f"/admin/projects/{project_id}/git-refresh",
        data={"project_id": str(project_id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert captured["project"] == project_id
    assert captured["action"] == "pull"
    assert b"Pulled latest changes" in response.data


def test_dashboard_orders_projects_by_last_activity(app, client, login_admin, monkeypatch):
    now = datetime(2024, 10, 30, 12, 0, tzinfo=timezone.utc)
    older = now.replace(hour=9)
    newer = now.replace(hour=13)

    monkeypatch.setattr("app.routes.admin.list_windows_for_aliases", lambda *_, **__: [])

    def fake_status(project):
        timestamp = newer.isoformat() if project.name == "fresh-project" else older.isoformat()
        return {
            "branch": "main",
            "dirty": False,
            "untracked_files": [],
            "status_summary": "",
            "last_commit_timestamp": timestamp,
            "last_pull": timestamp,
        }

    monkeypatch.setattr("app.routes.admin.get_repo_status", fake_status)

    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        user = User.query.filter_by(email="admin@example.com").first()

        stale_project = Project(
            name="stale-project",
            repo_url="git@example.com/stale.git",
            default_branch="main",
            tenant=tenant,
            owner=user,
            local_path="/tmp/stale",
        )
        fresh_project = Project(
            name="fresh-project",
            repo_url="git@example.com/fresh.git",
            default_branch="main",
            tenant=tenant,
            owner=user,
            local_path="/tmp/fresh",
        )
        integration = TenantIntegration(
            tenant=tenant,
            provider="jira",
            name="Jira Cloud",
            api_token="token",
            enabled=True,
            settings={"username": "user@example.com"},
        )
        fresh_link = ProjectIntegration(
            project=fresh_project,
            integration=integration,
            external_identifier="FRESH",
            last_synced_at=newer,
        )
        stale_link = ProjectIntegration(
            project=stale_project,
            integration=integration,
            external_identifier="STALE",
            last_synced_at=older,
        )
        db.session.add_all([stale_project, fresh_project, integration, fresh_link, stale_link])
        db.session.commit()

    response = client.get("/admin/")
    assert response.status_code == 200
    html = response.data.decode()
    assert html.index("fresh-project") < html.index("stale-project")
