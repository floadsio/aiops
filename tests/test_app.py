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
from app.services.issues import IssuePayload
from git import Repo


def test_app_factory():
    app = create_app()
    assert app.config["REPO_STORAGE_PATH"]
    client = app.test_client()
    root = client.get("/")
    assert root.status_code == 200
    response = client.get("/login")
    assert response.status_code == 200


def test_branch_badge_uses_recorded_marker(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'branch.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    instance_dir = tmp_path / "instance"
    app = create_app(TestConfig, instance_path=instance_dir)

    with app.app_context():
        db.create_all()
        marker = Path(app.instance_path) / "current_branch.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("release-2024-08\n", encoding="utf-8")

    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"branch: release-2024-08" in resp.data


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
        repo_path = tmp_path / "repos" / "demo-project"
        repo_path.mkdir(parents=True, exist_ok=True)
        repo = Repo.init(repo_path)
        (repo_path / "README.md").write_text("demo", encoding="utf-8")
        repo.index.add(["README.md"])
        repo.index.commit("Initial commit")
        repo.git.branch("-M", "main")
        (repo_path / "notes.md").write_text("notes", encoding="utf-8")
        repo.index.add(["notes.md"])
        repo.index.commit("Add notes")

        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(repo_path),
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
        repo_path = tmp_path / "repos" / "demo-project"
        repo_path.mkdir(parents=True, exist_ok=True)
        repo = Repo.init(repo_path)
        (repo_path / "README.md").write_text("demo", encoding="utf-8")
        repo.index.add(["README.md"])
        repo.index.commit("Initial commit")
        repo.git.branch("-M", "main")
        (repo_path / "notes.md").write_text("notes", encoding="utf-8")
        repo.index.add(["notes.md"])
        repo.index.commit("Add notes")
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(repo_path),
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
    assert "Issues" in body
    assert "Sample Issue" in body
    assert "GitLab Cloud" in body
    assert "group/demo" in body
    assert "Start Codex Session" in body
    assert "Recent Git History" in body
    assert "Initial commit" in body


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
        lambda project, session_name=None: SimpleNamespace(target="aiops:demo-window"),
    )

    response = client.post(f"/projects/{project_id}/issues/{issue_id}/prepare")
    assert response.status_code == 200
    data = response.get_json()
    assert data["tool"] == "codex"
    assert data["command"] == "codex"
    assert data["prompt"] == ""
    assert ":" in data["tmux_target"]

    local_context_path = Path(tmp_path / "repos" / "demo-project" / "AGENTS.override.md")
    assert local_context_path.exists()
    local_contents = local_context_path.read_text()
    assert "Sample Issue" in local_contents
    assert "Secondary Issue" in local_contents
    assert "## Git Identity" in local_contents
    assert "Owner" in local_contents
    assert "owner@example.com" in local_contents


def test_populate_agents_md_updates_context(tmp_path, monkeypatch):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'populate.db'}"
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

        # Seed a tracked AGENTS base file with a placeholder section.
        repo_root = Path(project.local_path)
        repo_root.mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text(
            (
                "# Demo Repository Guidelines\n\n"
                "## Current Issue Context\n"
                "<!-- issue-context:start -->\n\n"
                "_No content yet._\n\n"
                "<!-- issue-context:end -->\n"
            ),
            encoding="utf-8",
        )

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

    response = client.post(f"/projects/{project_id}/issues/{issue_id}/populate-agent-md")
    assert response.status_code == 200
    data = response.get_json()
    assert "tracked_path" in data
    assert "local_path" in data

    tracked_path = Path(data["tracked_path"])
    local_path = Path(data["local_path"])

    assert tracked_path == local_path

    assert tracked_path.exists()
    tracked_contents = tracked_path.read_text()
    assert "Sample Issue" in tracked_contents
    assert "Secondary Issue" in tracked_contents
    assert "_No content yet._" not in tracked_contents
    assert "<!-- issue-context:start -->" in tracked_contents
    assert "<!-- issue-context:end -->" in tracked_contents
    assert "## Git Identity" in tracked_contents
    assert "Owner" in tracked_contents
    assert "owner@example.com" in tracked_contents

    assert local_path.exists()
    local_contents = local_path.read_text()
    assert "Sample Issue" in local_contents
    assert "Secondary Issue" in local_contents
    assert "## Git Identity" in local_contents


def test_agents_editor_save_and_push(tmp_path, monkeypatch):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'agents.db'}"
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
        db.session.add_all([user, tenant, project])
        db.session.commit()

        agents_path = Path(project.local_path)
        agents_path.mkdir(parents=True, exist_ok=True)
        (agents_path / "AGENTS.override.md").write_text("Initial guide", encoding="utf-8")

        project_id = project.id

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    recorded: dict[str, object] = {}

    def fake_commit(project, files, message):
        recorded["commit"] = {
            "project_id": project.id,
            "files": [str(Path(path)) for path in files],
            "message": message,
        }
        return True

    def fake_push(project, action, ref=None, clean=False):
        recorded["push"] = {"project_id": project.id, "action": action}
        return "Push completed."

    monkeypatch.setattr("app.routes.projects.commit_project_files", fake_commit)
    monkeypatch.setattr("app.routes.projects.run_git_action", fake_push)

    response = client.get(f"/projects/{project_id}/agents")
    assert response.status_code == 200
    assert "Initial guide" in response.get_data(as_text=True)

    post_response = client.post(
        f"/projects/{project_id}/agents",
        data={
            "contents": "Rewritten guide",
            "commit_message": "Update AGENTS.override.md",
            "save_and_push": "1",
        },
        follow_redirects=True,
    )
    assert post_response.status_code == 200
    assert "Committed and pushed AGENTS.override.md." in post_response.get_data(as_text=True)
    assert "Push completed." in post_response.get_data(as_text=True)

    saved_text = (tmp_path / "repos" / "demo-project" / "AGENTS.override.md").read_text()
    assert "Rewritten guide" in saved_text

    assert recorded["commit"]["project_id"] == project_id
    assert "AGENTS.override.md" in recorded["commit"]["files"][0]
    assert recorded["commit"]["message"] == "Update AGENTS.override.md"
    assert recorded["push"]["action"] == "push"


def test_agents_editor_requires_commit_message(tmp_path, monkeypatch):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'agents2.db'}"
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
        db.session.add_all([user, tenant, project])
        db.session.commit()

        agents_path = Path(project.local_path)
        agents_path.mkdir(parents=True, exist_ok=True)
        (agents_path / "AGENTS.override.md").write_text("Initial guide", encoding="utf-8")

        project_id = project.id

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    commit_called = False

    def fake_commit(*_args, **_kwargs):
        nonlocal commit_called
        commit_called = True
        return True

    monkeypatch.setattr("app.routes.projects.commit_project_files", fake_commit)

    response = client.post(
        f"/projects/{project_id}/agents",
        data={
            "contents": "Rewritten guide",
            "commit_message": "",
            "save_and_push": "1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Commit message is required" in response.get_data(as_text=True)
    assert commit_called is False


def test_admin_issues_page_filters(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'issues_page.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig)

    with app.app_context():
        db.create_all()
        admin_user = User(
            email="admin@example.com",
            name="Admin",
            password_hash=hash_password("pass123"),
            is_admin=True,
        )
        tenant = Tenant(name="demo", description="Demo tenant")
        integration = TenantIntegration(
            tenant=tenant,
            provider="github",
            name="GitHub",
            api_token="token",
            enabled=True,
            settings={},
        )
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo-project"),
            tenant=tenant,
            owner=admin_user,
        )
        project_integration = ProjectIntegration(
            project=project,
            integration=integration,
            external_identifier="org/repo",
            config={},
        )
        open_issue = ExternalIssue(
            project_integration=project_integration,
            external_id="42",
            title="Fix deployment",
            status="open",
            labels=["infra"],
        )
        closed_issue = ExternalIssue(
            project_integration=project_integration,
            external_id="43",
            title="Retire legacy job",
            status="closed",
            labels=["cleanup"],
        )

        other_tenant = Tenant(name="ops", description="Ops tenant")
        other_integration = TenantIntegration(
            tenant=other_tenant,
            provider="github",
            name="Ops GitHub",
            api_token="token",
            enabled=True,
            settings={},
        )
        other_project = Project(
            name="ops-project",
            repo_url="git@example.com/ops.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "ops-project"),
            tenant=other_tenant,
            owner=admin_user,
        )
        other_project_integration = ProjectIntegration(
            project=other_project,
            integration=other_integration,
            external_identifier="ops/repo",
            config={},
        )
        other_issue = ExternalIssue(
            project_integration=other_project_integration,
            external_id="88",
            title="Provision runner",
            status="open",
            labels=["ops"],
        )

        db.session.add_all([
            admin_user,
            tenant,
            integration,
            project,
            project_integration,
            open_issue,
            closed_issue,
            other_tenant,
            other_integration,
            other_project,
            other_project_integration,
            other_issue,
        ])
        db.session.commit()

        tenant_id = tenant.id
        other_tenant_id = other_tenant.id

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    response = client.get("/admin/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Fix deployment" in body
    assert "Retire legacy job</" not in body
    assert "Provision runner" in body
    assert "issue-tenant-filter" in body
    assert "Start Codex Session" in body
    assert "Populate AGENTS.override.md" in body
    assert "Close Issue" in body

    response_closed = client.get("/admin/issues?status=closed")
    assert response_closed.status_code == 200
    body_closed = response_closed.get_data(as_text=True)
    assert "Retire legacy job</" in body_closed
    assert "Fix deployment</" not in body_closed
    assert "Provision runner" not in body_closed
    assert "Start Codex Session" in body_closed
    assert "Populate AGENTS.override.md" in body_closed
    assert "Close Issue" not in body_closed

    response_all = client.get("/admin/issues?status=all")
    body_all = response_all.get_data(as_text=True)
    assert "Fix deployment" in body_all
    assert "Retire legacy job" in body_all
    assert "Provision runner" in body_all

    response_tenant = client.get(f"/admin/issues?tenant={tenant_id}")
    body_tenant = response_tenant.get_data(as_text=True)
    assert "Fix deployment" in body_tenant
    assert "Retire legacy job" not in body_tenant
    assert "Provision runner" not in body_tenant

    response_other_tenant = client.get(f"/admin/issues?tenant={other_tenant_id}&status=all")
    body_other = response_other_tenant.get_data(as_text=True)
    assert "Provision runner" in body_other
    assert "Fix deployment" not in body_other


def test_close_issue_route_updates_status(tmp_path, monkeypatch):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'close_issue.db'}"
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
        integration = TenantIntegration(
            tenant=tenant,
            provider="github",
            name="GitHub",
            api_token="token",
            enabled=True,
            settings={},
        )
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo-project"),
            tenant=tenant,
            owner=user,
        )
        project_integration = ProjectIntegration(
            project=project,
            integration=integration,
            external_identifier="org/repo",
            config={},
        )
        issue = ExternalIssue(
            project_integration=project_integration,
            external_id="42",
            title="Fix bug",
            status="open",
            labels=[],
        )
        db.session.add_all([user, tenant, integration, project, project_integration, issue])
        db.session.commit()

        project_id = project.id
        issue_id = issue.id

    def fake_close(project_integration_obj, external_id):
        assert external_id == "42"
        return IssuePayload(
            external_id="42",
            title="Fix bug",
            status="closed",
            assignee=None,
            url="https://github.com/org/repo/issues/42",
            labels=["bug"],
            external_updated_at=datetime(2024, 10, 20, 12, 0, tzinfo=timezone.utc),
            raw={"state": "closed"},
        )

    monkeypatch.setattr("app.routes.projects.close_issue_for_project_integration", fake_close)

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    response = client.post(
        f"/projects/{project_id}/issues/{issue_id}/close",
        data={},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Closed issue 42" in response.get_data(as_text=True)

    with app.app_context():
        updated_issue = ExternalIssue.query.get(issue_id)
        assert updated_issue.status == "closed"
        assert updated_issue.labels == ["bug"]


def test_assign_issue_route_updates_assignee(tmp_path, monkeypatch):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'assign_issue.db'}"
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
        integration = TenantIntegration(
            tenant=tenant,
            provider="github",
            name="GitHub",
            api_token="token",
            enabled=True,
            settings={},
        )
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo-project"),
            tenant=tenant,
            owner=user,
        )
        project_integration = ProjectIntegration(
            project=project,
            integration=integration,
            external_identifier="org/repo",
            config={},
        )
        issue = ExternalIssue(
            project_integration=project_integration,
            external_id="42",
            title="Fix bug",
            status="open",
            labels=["bug"],
        )
        db.session.add_all([user, tenant, integration, project, project_integration, issue])
        db.session.commit()

        project_id = project.id
        issue_id = issue.id

    def fake_assign(project_integration_obj, external_id, assignees):
        assert external_id == "42"
        assert assignees == ["octocat"]
        return IssuePayload(
            external_id="42",
            title="Fix bug",
            status="open",
            assignee="octocat",
            url="https://github.com/org/repo/issues/42",
            labels=["bug"],
            external_updated_at=datetime(2024, 10, 21, 12, 0, tzinfo=timezone.utc),
            raw={"assignee": "octocat"},
        )

    monkeypatch.setattr("app.routes.projects.assign_issue_for_project_integration", fake_assign)

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    response = client.post(
        f"/projects/{project_id}/issues/{issue_id}/assign",
        data={"assignee": "octocat"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Assigned issue 42 to octocat" in response.get_data(as_text=True)

    with app.app_context():
        updated_issue = ExternalIssue.query.get(issue_id)
        assert updated_issue.assignee == "octocat"


def test_close_tmux_window_route(tmp_path, monkeypatch):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'close_tmux.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig)

    with app.app_context():
        db.create_all()
        user = User(
            email="close@example.com",
            name="Closer",
            password_hash=hash_password("pass123"),
            is_admin=True,
        )
        tenant = Tenant(name="close-tenant", description="Demo tenant")
        repo_path = tmp_path / "repos" / "close-project"
        repo_path.mkdir(parents=True, exist_ok=True)
        project = Project(
            name="close-project",
            repo_url="git@example.com/close.git",
            default_branch="main",
            local_path=str(repo_path),
            tenant=tenant,
            owner=user,
        )
        db.session.add_all([user, tenant, project])
        db.session.commit()
        project_id = project.id

    client = app.test_client()
    login_resp = client.post(
        "/login",
        data={"email": "close@example.com", "password": "pass123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    recorded = {}

    def fake_close(target):
        recorded["target"] = target

    monkeypatch.setattr("app.routes.projects.close_tmux_target", fake_close)

    response = client.post(
        f"/projects/{project_id}/tmux/close",
        data={"tmux_target": "demo:window", "next": "/admin/"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert recorded.get("target") == "demo:window"


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
