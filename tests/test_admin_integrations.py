from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from git import Repo
from git.exc import GitCommandError

import pytest

from app import create_app, db
from app.config import Config
from app.models import Project, ProjectIntegration, SSHKey, Tenant, TenantIntegration, User
from app.security import hash_password
from app.services.key_service import resolve_private_key_path
from app.services.update_service import UpdateError
from app.services.tmux_service import TmuxServiceError
from app.services.gemini_update_service import GeminiUpdateError
from app.services.gemini_config_service import GeminiConfigError
from app.services.codex_config_service import CodexConfigError
from app.services.claude_update_service import ClaudeUpdateError
from app.services.claude_config_service import ClaudeConfigError
from app.services.git_service import checkout_or_create_branch
from app.services.migration_service import MigrationError


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


@pytest.fixture()
def admin_user_id(app):
    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user is not None
        return user.id


def _create_project(app, name="demo-branch"):
    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        user = User.query.filter_by(email="admin@example.com").first()
        assert tenant is not None and user is not None
        repo_dir = Path(app.config["REPO_STORAGE_PATH"]) / name
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo = Repo.init(repo_dir)
        readme = repo_dir / "README.md"
        readme.write_text("demo", encoding="utf-8")
        repo.index.add([str(readme)])
        repo.index.commit("init")
        current_branch = None
        try:
            current_branch = repo.active_branch.name
        except TypeError:
            current_branch = None
        if current_branch != "main":
            try:
                repo.git.checkout("-b", "main")
            except GitCommandError:
                repo.git.checkout("main")
        repo.git.branch("feature/demo")

        project = Project(
            name=name,
            repo_url="git@example.com/demo.git",
            default_branch="main",
            tenant=tenant,
            owner=user,
            local_path=str(repo_dir),
        )
        db.session.add(project)
        db.session.commit()
        return project.id


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

    def fake_run_update(**kwargs):
        calls["invoked"] = True
        return DummyResult()

    monkeypatch.setattr("app.routes.admin.run_update_script", fake_run_update)

    restart_calls = {}

    def fake_trigger(command):
        restart_calls["command"] = command
        return True, "Restart scheduled"

    monkeypatch.setattr("app.routes.admin._trigger_restart", fake_trigger)
    app.config["UPDATE_RESTART_COMMAND"] = None

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
    def fake_run_update(**kwargs):
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

    monkeypatch.setattr("app.routes.admin.run_update_script", lambda **_: DummyResult())
    monkeypatch.setattr("app.routes.admin._trigger_restart", lambda cmd: (False, "Restart failed"))

    response = client.post(
        "/admin/system/update",
        data={"restart": "y", "submit": "Run update script"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Restart failed" in response.data


def test_admin_can_run_migrations(app, client, login_admin, monkeypatch):
    class DummyResult:
        command = "flask --app manage.py db upgrade"
        returncode = 0
        stdout = "migrated"
        stderr = ""

        @property
        def ok(self):
            return True

    calls = {}

    def fake_run_migrations():
        calls["invoked"] = True
        return DummyResult()

    monkeypatch.setattr("app.routes.admin.run_db_upgrade", fake_run_migrations)

    response = client.post(
        "/admin/settings/migrations/run",
        data={"submit": "Run migrations"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert calls.get("invoked") is True
    assert b"Database migrations succeeded" in response.data
    assert b"update-log" in response.data


def test_admin_migration_error(app, client, login_admin, monkeypatch):
    def fake_run_migrations():
        raise MigrationError("flask not found")

    monkeypatch.setattr("app.routes.admin.run_db_upgrade", fake_run_migrations)

    response = client.post(
        "/admin/settings/migrations/run",
        data={"submit": "Run migrations"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"flask not found" in response.data


def test_admin_tmux_resync_success(app, client, login_admin, monkeypatch):
    class DummyResult:
        created = 2
        removed = 1
        total_managed = 5

    calls = {}

    def fake_sync(projects, session_name=None):
        calls["count"] = len(projects)
        return DummyResult()

    monkeypatch.setattr("app.routes.admin.sync_project_windows", fake_sync)

    response = client.post(
        "/admin/settings/tmux/resync",
        data={"submit": "Resync tmux windows"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert calls.get("count") is not None
    assert b"Synced tmux windows" in response.data


def test_admin_tmux_resync_error(app, client, login_admin, monkeypatch):
    def fake_sync(projects, session_name=None):
        raise TmuxServiceError("tmux unavailable")

    monkeypatch.setattr("app.routes.admin.sync_project_windows", fake_sync)

    response = client.post(
        "/admin/settings/tmux/resync",
        data={"submit": "Resync tmux windows"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"tmux unavailable" in response.data


def test_admin_gemini_update_success(app, client, login_admin, monkeypatch):
    class DummyResult:
        command = "sudo npm install -g @google/gemini-cli"
        returncode = 0
        stdout = "ok"
        stderr = ""

        @property
        def ok(self):
            return True

    monkeypatch.setattr("app.routes.admin.install_latest_gemini", lambda: DummyResult())

    response = client.post(
        "/admin/settings/gemini/update",
        data={"submit": "Install latest Gemini"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Gemini CLI update succeeded" in response.data


def test_admin_gemini_update_failure(app, client, login_admin, monkeypatch):
    def fake_update():
        raise GeminiUpdateError("npm missing")

    monkeypatch.setattr("app.routes.admin.install_latest_gemini", fake_update)

    response = client.post(
        "/admin/settings/gemini/update",
        data={"submit": "Install latest Gemini"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"npm missing" in response.data


def test_admin_gemini_accounts_save(app, client, login_admin, admin_user_id, monkeypatch):
    saved = {}

    def fake_save(payload, *, user_id=None):
        saved["payload"] = payload
        saved["user_id"] = user_id

    monkeypatch.setattr("app.routes.admin.save_google_accounts", fake_save)

    response = client.post(
        "/admin/settings/gemini/accounts",
        data={"payload": "{}", "user_id": str(admin_user_id), "next": "/admin/settings"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert saved["payload"] == "{}"
    assert saved["user_id"] == admin_user_id


def test_admin_gemini_accounts_error(app, client, login_admin, admin_user_id, monkeypatch):
    def fake_save(payload, *, user_id=None):
        raise GeminiConfigError("bad json")

    monkeypatch.setattr("app.routes.admin.save_google_accounts", fake_save)

    response = client.post(
        "/admin/settings/gemini/accounts",
        data={"payload": "{}", "user_id": str(admin_user_id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"bad json" in response.data


def test_admin_gemini_oauth_save(app, client, login_admin, admin_user_id, monkeypatch):
    saved = {}

    def fake_save(payload, *, user_id=None):
        saved["payload"] = payload
        saved["user_id"] = user_id

    monkeypatch.setattr("app.routes.admin.save_oauth_creds", fake_save)

    response = client.post(
        "/admin/settings/gemini/oauth",
        data={"payload": "{}", "user_id": str(admin_user_id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert saved["payload"] == "{}"
    assert saved["user_id"] == admin_user_id


def test_admin_gemini_oauth_error(app, client, login_admin, admin_user_id, monkeypatch):
    def fake_save(payload, *, user_id=None):
        raise GeminiConfigError("invalid")

    monkeypatch.setattr("app.routes.admin.save_oauth_creds", fake_save)

    response = client.post(
        "/admin/settings/gemini/oauth",
        data={"payload": "{}", "user_id": str(admin_user_id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"invalid" in response.data


def test_admin_gemini_settings_save(app, client, login_admin, admin_user_id, monkeypatch):
    saved = {}

    def fake_save(payload, *, user_id=None):
        saved["payload"] = payload
        saved["user_id"] = user_id

    monkeypatch.setattr("app.routes.admin.save_settings_json", fake_save)

    response = client.post(
        "/admin/settings/gemini/settings",
        data={"payload": "{}", "user_id": str(admin_user_id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert saved["payload"] == "{}"
    assert saved["user_id"] == admin_user_id


def test_admin_gemini_settings_error(app, client, login_admin, admin_user_id, monkeypatch):
    def fake_save(payload, *, user_id=None):
        raise GeminiConfigError("broken settings")

    monkeypatch.setattr("app.routes.admin.save_settings_json", fake_save)

    response = client.post(
        "/admin/settings/gemini/settings",
        data={"payload": "{}", "user_id": str(admin_user_id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"broken settings" in response.data


def test_admin_claude_update_success(app, client, login_admin, monkeypatch):
    class DummyResult:
        command = "sudo npm install -g @anthropic-ai/claude-code"
        returncode = 0
        stdout = "ok"
        stderr = ""

        @property
        def ok(self):
            return True

    monkeypatch.setattr("app.routes.admin.install_latest_claude", lambda: DummyResult())

    response = client.post(
        "/admin/settings/claude/update",
        data={"submit": "Install latest Claude"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Claude CLI update succeeded" in response.data


def test_admin_claude_update_failure(app, client, login_admin, monkeypatch):
    def fake_update():
        raise ClaudeUpdateError("npm missing")

    monkeypatch.setattr("app.routes.admin.install_latest_claude", fake_update)

    response = client.post(
        "/admin/settings/claude/update",
        data={"submit": "Install latest Claude"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"npm missing" in response.data


def test_admin_claude_key_save(app, client, login_admin, admin_user_id, monkeypatch):
    saved = {}

    def fake_save(payload, *, user_id=None):
        saved["payload"] = payload
        saved["user_id"] = user_id

    monkeypatch.setattr("app.routes.admin.save_claude_api_key", fake_save)

    response = client.post(
        "/admin/settings/claude/key",
        data={"payload": "token", "user_id": str(admin_user_id), "next": "/admin/settings"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert saved["payload"] == "token"
    assert saved["user_id"] == admin_user_id


def test_admin_claude_key_error(app, client, login_admin, admin_user_id, monkeypatch):
    def fake_save(payload, *, user_id=None):
        raise ClaudeConfigError("invalid key")

    monkeypatch.setattr("app.routes.admin.save_claude_api_key", fake_save)

    response = client.post(
        "/admin/settings/claude/key",
        data={"payload": "token", "user_id": str(admin_user_id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"invalid key" in response.data


def test_admin_codex_auth_save(app, client, login_admin, admin_user_id, monkeypatch):
    captured = {}

    def fake_save(payload, user_id=None):
        captured["payload"] = payload
        captured["user_id"] = user_id

    monkeypatch.setattr("app.routes.admin.save_codex_auth", fake_save)

    response = client.post(
        "/admin/settings/codex/auth",
        data={"payload": "{}", "user_id": str(admin_user_id), "next": "/admin/settings"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert captured["payload"] == "{}"
    assert captured["user_id"] == admin_user_id


def test_admin_codex_auth_error(app, client, login_admin, admin_user_id, monkeypatch):
    def fake_save(payload, user_id=None):
        raise CodexConfigError("bad codex auth")

    monkeypatch.setattr("app.routes.admin.save_codex_auth", fake_save)

    response = client.post(
        "/admin/settings/codex/auth",
        data={"payload": "{}", "user_id": str(admin_user_id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"bad codex auth" in response.data


def test_admin_project_branch_checkout(app, client, login_admin, monkeypatch):
    project_id = _create_project(app)
    calls = {}

    def fake_checkout(project, branch, base):
        calls["project"] = project.id
        calls["branch"] = branch
        calls["base"] = base
        return True

    monkeypatch.setattr("app.routes.admin.checkout_or_create_branch", fake_checkout)

    response = client.post(
        f"/admin/projects/{project_id}/branch/manage",
        data={
            "project_id": str(project_id),
            "branch_name": "feature/demo",
            "base_branch": "main",
            "checkout_submit": "Checkout/Create",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert calls["project"] == project_id
    assert calls["branch"] == "feature/demo"
    assert calls["base"] == "main"
    assert b"Created branch feature/demo" in response.data


def test_admin_project_branch_merge(app, client, login_admin, monkeypatch):
    project_id = _create_project(app, name="demo-merge")
    calls = {}

    def fake_merge(project, source, target):
        calls["project"] = project.id
        calls["source"] = source
        calls["target"] = target

    monkeypatch.setattr("app.routes.admin.merge_branch", fake_merge)

    response = client.post(
        f"/admin/projects/{project_id}/branch/manage",
        data={
            "project_id": str(project_id),
            "merge_source": "feature/demo",
            "merge_target": "main",
            "merge_submit": "Merge Branch",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert calls["project"] == project_id
    assert calls["source"] == "feature/demo"
    assert calls["target"] == "main"
    assert b"Merged feature/demo into main" in response.data


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

    def fake_sync(link, **kwargs):
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
        captured["clean"] = clean
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
    assert captured["clean"] is False
    assert b"Pulled latest changes" in response.data


def test_admin_can_clean_pull_project_repo(app, client, login_admin, tmp_path, monkeypatch):
    with app.app_context():
        tenant = Tenant.query.filter_by(name="tenant-one").first()
        user = User.query.filter_by(email="admin@example.com").first()
        project = Project(
            name="git-clean-refresh",
            repo_url="git@example.com/git-clean-refresh.git",
            default_branch="main",
            tenant=tenant,
            owner=user,
            local_path=str(tmp_path / "git-clean-refresh"),
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    captured = {}

    def fake_run(project_obj, action, ref=None, clean=False):
        captured["project"] = project_obj.id
        captured["action"] = action
        captured["clean"] = clean
        return "Clean Pull"

    monkeypatch.setattr("app.routes.admin.run_git_action", fake_run)

    response = client.post(
        f"/admin/projects/{project_id}/git-refresh",
        data={"project_id": str(project_id), "clean_submit": "Clean Pull"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert captured["project"] == project_id
    assert captured["action"] == "pull"
    assert captured["clean"] is True
    assert b"Clean pull completed" in response.data


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


def test_dashboard_tenant_filter_limits_projects(app, client, login_admin, monkeypatch, tmp_path):
    monkeypatch.setattr("app.routes.admin.list_windows_for_aliases", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.routes.admin.get_repo_status", lambda project: {})

    with app.app_context():
        tenant_one = Tenant.query.filter_by(name="tenant-one").first()
        user = User.query.filter_by(email="admin@example.com").first()
        tenant_two = Tenant(name="tenant-two", description="Tenant Two")
        tenant_three = Tenant(name="tenant-three", description="Tenant Three")
        project_alpha = Project(
            name="alpha-project",
            repo_url="git@example.com/alpha.git",
            default_branch="main",
            tenant=tenant_one,
            owner=user,
            local_path=str(tmp_path / "alpha"),
        )
        project_beta = Project(
            name="beta-project",
            repo_url="git@example.com/beta.git",
            default_branch="main",
            tenant=tenant_two,
            owner=user,
            local_path=str(tmp_path / "beta"),
        )
        db.session.add_all([tenant_two, tenant_three, project_alpha, project_beta])
        db.session.commit()
        tenant_two_id = tenant_two.id
        tenant_three_id = tenant_three.id

    response = client.get(f"/admin/?tenant={tenant_two_id}")
    assert response.status_code == 200
    html = response.data.decode()
    assert "beta-project" in html
    assert "alpha-project" not in html
    assert f"Filtered by {tenant_two.name}" in html

    response_empty = client.get(f"/admin/?tenant={tenant_three_id}")
    assert response_empty.status_code == 200
    empty_html = response_empty.data.decode()
    assert "No projects match the selected tenant." in empty_html
    assert "Clear filter" in empty_html
