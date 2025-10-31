from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app import create_app, db
from app.config import Config
from app.models import (
    ExternalIssue,
    Project,
    ProjectIntegration,
    SSHKey,
    Tenant,
    TenantIntegration,
    User,
)
from app.security import hash_password
from app.services.ansible_runner import run_ansible_playbook
from app.services.key_service import resolve_private_key_path


def test_app_factory():
    app = create_app()
    assert app.config["REPO_STORAGE_PATH"]
    client = app.test_client()
    root = client.get("/")
    assert root.status_code == 200
    response = client.get("/login")
    assert response.status_code == 200


def test_seed_command(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        db.create_all()
        user = User(
            email="seed@example.com",
            name="Seed User",
            password_hash=hash_password("password123"),
            is_admin=True,
        )
        db.session.add(user)
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed-data", "--owner-email", "seed@example.com"])
    assert result.exit_code == 0, result.output

    with app.app_context():
        tenant = Tenant.query.filter_by(name="dcx").first()
        project = Project.query.filter_by(name="flamelet-dcx").first()
        assert tenant is not None
        assert project is not None
        assert project.owner.email == "seed@example.com"
        assert Path(project.local_path).name == "flamelet-dcx"
        assert Tenant.query.filter_by(name="iwf").first() is not None
        assert Tenant.query.filter_by(name="kbe").first() is not None
        assert Project.query.filter_by(name="flamelet-iwf").first() is not None
        assert Project.query.filter_by(name="flamelet-kbe").first() is not None


def test_seed_identities_command(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'identities.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    instance_dir = tmp_path / "instance"
    key_source = tmp_path / "syseng"
    key_source.mkdir(parents=True)

    private_key_path = key_source / "id_rsa-dcx-prod-syseng"
    private_key_path.write_text(
        """-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n"""
    )
    (key_source / "id_rsa-dcx-prod-syseng.pub").write_text(
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBuJrVN6a8GN28AL5OHnqd7qV3CyMfCVx/gv3BP/laZT test@example.com"
    )

    app = create_app(TestConfig, instance_path=instance_dir)

    with app.app_context():
        db.create_all()
        user = User(
            email="syseng@example.com",
            name="SysEng",
            password_hash=hash_password("password123"),
            is_admin=True,
        )
        db.session.add(user)
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=[
            "seed-identities",
            "--owner-email",
            "syseng@example.com",
            "--source-dir",
            str(key_source),
        ]
    )
    assert result.exit_code == 0, result.output

    with app.app_context():
        ssh_key = SSHKey.query.filter_by(name="syseng-dcx-prod").first()
        tenant = Tenant.query.filter_by(name="dcx").first()
        assert ssh_key is not None
        assert tenant is not None
        assert ssh_key.tenant_id == tenant.id
        assert ssh_key.private_key_path
        stored_path = resolve_private_key_path(ssh_key.private_key_path)
        assert stored_path is not None
        assert stored_path.exists()
        assert stored_path.read_text() == private_key_path.read_text()


def test_project_consoles(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'console.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        db.create_all()
        user = User(
            email="owner@example.com",
            name="Owner",
            password_hash=hash_password("pass123"),
            is_admin=True,
        )
        tenant = Tenant(name="demo", description="Demo tenant")
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo-project"),
            tenant=tenant,
            owner=user,
        )
        db.session.add_all([user, tenant, project])
        db.session.commit()

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    with app.app_context():
        project_id = Project.query.filter_by(name="demo-project").first().id

    ai_resp = client.get(f"/projects/{project_id}/ai")
    assert ai_resp.status_code == 200

    ansible_resp = client.get(f"/projects/{project_id}/ansible")
    assert ansible_resp.status_code == 200
    assert b"Semaphore Project ID" in ansible_resp.data


def test_project_detail_shows_external_issues(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'issues.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig)

    with app.app_context():
        db.create_all()
        user = User(
            email="owner@example.com",
            name="Owner",
            password_hash=hash_password("pass123"),
            is_admin=True,
        )
        tenant = Tenant(name="demo", description="Demo tenant")
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo-project"),
            tenant=tenant,
            owner=user,
        )
        integration = TenantIntegration(
            tenant=tenant,
            provider="gitlab",
            name="GitLab Cloud",
            api_token="token",
            enabled=True,
            settings={},
        )
        project_integration = ProjectIntegration(
            project=project,
            integration=integration,
            external_identifier="group/demo",
            config={},
            last_synced_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        issue = ExternalIssue(
            project_integration=project_integration,
            external_id="123",
            title="Sample Issue",
            status="opened",
            assignee="alice",
            url="https://gitlab.example/project/issues/123",
            labels=["bug", "urgent"],
            external_updated_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        db.session.add_all([user, tenant, project, integration, project_integration, issue])
        db.session.commit()
        project_id = project.id

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    with app.app_context():
        project_id = Project.query.filter_by(name="demo-project").first().id

    detail_resp = client.get(f"/projects/{project_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.data.decode()
    assert "External Issues" in body
    assert "Sample Issue" in body
    assert "GitLab Cloud" in body
    assert "group/demo" in body
    assert "Start Codex Session" in body


def test_prepare_issue_context_creates_agent(tmp_path, monkeypatch):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'issues.db'}"
        REPO_STORAGE_PATH = str(tmp_path / 'repos')

    app = create_app(TestConfig)

    with app.app_context():
        db.create_all()
        user = User(
            email="owner@example.com",
            name="Owner",
            password_hash=hash_password("pass123"),
            is_admin=True,
        )
        tenant = Tenant(name="demo", description="Demo tenant")
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo-project"),
            tenant=tenant,
            owner=user,
        )
        integration = TenantIntegration(
            tenant=tenant,
            provider="gitlab",
            name="GitLab Cloud",
            api_token="token",
            enabled=True,
            settings={},
        )
        project_integration = ProjectIntegration(
            project=project,
            integration=integration,
            external_identifier="group/demo",
            config={},
        )
        issue = ExternalIssue(
            project_integration=project_integration,
            external_id="123",
            title="Sample Issue",
            status="opened",
        )
        other_issue = ExternalIssue(
            project_integration=project_integration,
            external_id="456",
            title="Secondary Issue",
            status="closed",
        )
        db.session.add_all([user, tenant, project, integration, project_integration, issue, other_issue])
        db.session.commit()

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    with app.app_context():
        project_id = Project.query.filter_by(name="demo-project").first().id
        issue_id = ExternalIssue.query.filter_by(external_id="123").first().id

    monkeypatch.setattr(
        "app.routes.projects.get_or_create_window_for_project",
        lambda project: SimpleNamespace(target="aiops:demo-window"),
    )

    response = client.post(f"/projects/{project_id}/issues/{issue_id}/prepare")
    assert response.status_code == 200
    data = response.get_json()
    assert data["tool"] == "codex"
    assert "--agent" in data["command"]
    assert "Secondary Issue" in data["prompt"]
    assert "->" in data["prompt"]
    assert ":" in data["tmux_target"]
    agent_path = Path(data["agent_path"])
    assert agent_path.exists()
    assert "Sample Issue" in agent_path.read_text()
    assert "Secondary Issue" in agent_path.read_text()


def test_run_ansible_playbook_uses_semaphore(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'semaphore.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        SEMAPHORE_BASE_URL = "https://sem.example"
        SEMAPHORE_API_TOKEN = "token-123"
        SEMAPHORE_POLL_INTERVAL = 0.0
        SEMAPHORE_TASK_TIMEOUT = 5.0

    app = create_app(TestConfig)

    with app.app_context():
        captured_payload = {}

        class StubSemaphoreClient:
            def start_task(self, project_id, template_id, payload):
                captured_payload.update(payload)
                assert project_id == 42
                assert template_id == 7
                return {"id": 101, "status": "waiting"}

            def wait_for_task(self, project_id, task_id, poll_interval=0, timeout=0):
                assert project_id == 42
                assert task_id == 101
                assert poll_interval == app.config["SEMAPHORE_POLL_INTERVAL"]
                assert timeout == app.config["SEMAPHORE_TASK_TIMEOUT"]
                return {"id": task_id, "status": "success", "playbook": "deploy.yml"}

            def get_task_output(self, project_id, task_id):
                assert project_id == 42
                assert task_id == 101
                return "PLAY RECAP: ok=3 changed=1"

        monkeypatch.setattr(
            "app.services.ansible_runner._get_semaphore_client",
            lambda: StubSemaphoreClient(),
        )

        result = run_ansible_playbook(
            "demo-project",
            42,
            7,
            playbook="deploy.yml",
            arguments='{"env": "staging"}',
            git_branch="main",
            message="Triggered from test",
            dry_run=True,
            debug=True,
            diff=True,
            limit="all",
            inventory_id=9,
        )

        assert result["returncode"] == 0
        assert result["stdout"].startswith("PLAY RECAP")
        assert result["task_id"] == 101
        assert result["template_id"] == 7
        assert result["semaphore_project_id"] == 42

        assert captured_payload["playbook"] == "deploy.yml"
        assert captured_payload["arguments"] == '{"env": "staging"}'
        assert captured_payload["git_branch"] == "main"
        assert captured_payload["message"] == "Triggered from test"
        assert captured_payload["dry_run"] is True
        assert captured_payload["debug"] is True
        assert captured_payload["diff"] is True
        assert captured_payload["limit"] == "all"
        assert captured_payload["inventory_id"] == 9
