from __future__ import annotations

from pathlib import Path

import pytest
from git import GitCommandError, Repo

from app import create_app, db
from app.config import Config
from app.models import Project, SSHKey, Tenant, User
from app.security import hash_password
from app.services.git_service import (
    _resolve_project_ssh_key_path,
    delete_project_branch,
    ensure_repo_checkout,
)


@pytest.fixture()
def app(tmp_path):
    class _Config(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'git.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    application = create_app(_Config, instance_path=tmp_path / "instance")
    with application.app_context():
        db.create_all()
        user = User(
            email="owner@example.com",
            name="Owner",
            password_hash=hash_password("secret"),
            is_admin=True,
        )
        tenant = Tenant(name="demo-tenant", description="Demo tenant")
        db.session.add_all([user, tenant])
        db.session.commit()
    return application


@pytest.fixture()
def owner(app):
    with app.app_context():
        return User.query.filter_by(email="owner@example.com").first()


@pytest.fixture()
def tenant(app):
    with app.app_context():
        return Tenant.query.filter_by(name="demo-tenant").first()


def test_resolve_project_ssh_key_prefers_project_key(app, owner, tenant, tmp_path):
    private_path = tmp_path / "keys" / "id_rsa"
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(
        """-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n""",
        encoding="utf-8",
    )

    with app.app_context():
        project_key = SSHKey(
            name="project-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCproject",
            fingerprint="project-fingerprint",
            user=owner,
            tenant=tenant,
            private_key_path=str(private_path),
        )
        tenant_key = SSHKey(
            name="tenant-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCtenant",
            fingerprint="tenant-fingerprint",
            user=owner,
            tenant=tenant,
            private_key_path=str(tmp_path / "keys" / "id_rsa_tenant"),
        )
        (tmp_path / "keys" / "id_rsa_tenant").write_text(
            """-----BEGIN OPENSSH PRIVATE KEY-----\nBBBB\n-----END OPENSSH PRIVATE KEY-----\n""",
            encoding="utf-8",
        )
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo"),
            tenant=tenant,
            owner=owner,
            ssh_key=project_key,
        )
        db.session.add_all([project_key, tenant_key, project])
        db.session.commit()
        assert _resolve_project_ssh_key_path(project) == str(private_path)


def test_resolve_skips_invalid_private_key(app, owner, tenant, tmp_path):
    tenant_key_path = tmp_path / "keys" / "tenant_valid"
    tenant_key_path.parent.mkdir(parents=True, exist_ok=True)
    tenant_key_path.write_text(
        """-----BEGIN OPENSSH PRIVATE KEY-----\nTENANT\n-----END OPENSSH PRIVATE KEY-----\n""",
        encoding="utf-8",
    )

    project_key_path = tmp_path / "keys" / "project_invalid"
    project_key_path.write_text("INVALID CONTENT", encoding="utf-8")

    with app.app_context():
        tenant_key = SSHKey(
            name="tenant-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCtenant2",
            fingerprint="tenant-fingerprint-2",
            user=owner,
            tenant=tenant,
            private_key_path=str(tenant_key_path),
        )
        project_key = SSHKey(
            name="project-key-invalid",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCproject-invalid",
            fingerprint="project-fingerprint-invalid",
            user=owner,
            tenant=tenant,
            private_key_path=str(project_key_path),
        )
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo"),
            tenant=tenant,
            owner=owner,
            ssh_key=project_key,
        )
        db.session.add_all([tenant_key, project_key, project])
        db.session.commit()
        resolved = _resolve_project_ssh_key_path(project)
        assert resolved == str(tenant_key_path)


def test_ensure_repo_checkout_uses_ssh_env(app, owner, tenant, tmp_path, monkeypatch):
    private_path = tmp_path / "keys" / "id_rsa_project"
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(
        """-----BEGIN OPENSSH PRIVATE KEY-----\nCCCC\n-----END OPENSSH PRIVATE KEY-----\n""",
        encoding="utf-8",
    )
    tenant_key_path = tmp_path / "keys" / "tenant_valid"
    tenant_key_path.write_text(
        """-----BEGIN OPENSSH PRIVATE KEY-----\nTENANT\n-----END OPENSSH PRIVATE KEY-----\n""",
        encoding="utf-8",
    )

    with app.app_context():
        project_key = SSHKey(
            name="project-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCproject2",
            fingerprint="project-fingerprint-2",
            user=owner,
            tenant=tenant,
            private_key_path=str(private_path),
        )
        tenant_key = SSHKey(
            name="tenant-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCtenant4",
            fingerprint="tenant-fingerprint-4",
            user=owner,
            tenant=tenant,
            private_key_path=str(tenant_key_path),
        )
        project = Project(
            name="demo-project",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "demo"),
            tenant=tenant,
            owner=owner,
            ssh_key=project_key,
        )
        db.session.add_all([project_key, tenant_key, project])
        db.session.commit()

        captured_env: dict[str, str] = {}
        attempts: list[str] = []

        class DummyRepo:
            def __init__(self, repo_path: Path):
                self.path = Path(repo_path)
                self.git_dir = self.path / ".git"
                self.git = self

            @classmethod
            def clone_from(cls, repo_url, path, branch=None, env=None):
                captured_env.update(env or {})
                attempts.append(env.get("GIT_SSH_COMMAND", ""))
                if (
                    env
                    and "project" in env.get("GIT_SSH_COMMAND", "")
                    and len(attempts) == 1
                ):
                    raise GitCommandError(
                        "clone", 128, stderr="Load key invalid format"
                    )
                path = Path(path)
                path.mkdir(parents=True, exist_ok=True)
                (path / ".git").mkdir(parents=True, exist_ok=True)
                return cls(path)

            def custom_environment(self, **kwargs):
                class _Ctx:
                    def __enter__(self_inner):
                        return None

                    def __exit__(self_inner, exc_type, exc_val, exc_tb):
                        return False

                return _Ctx()

        monkeypatch.setattr("app.services.git_service.Repo", DummyRepo)

        repo = ensure_repo_checkout(project)
        assert repo.git_dir.exists()
        assert "GIT_SSH_COMMAND" in captured_env
        command = captured_env["GIT_SSH_COMMAND"]
        assert str(tenant_key_path) in command
        assert "StrictHostKeyChecking=accept-new" in command
        known_hosts_path = Path(app.instance_path) / "known_hosts"
        assert known_hosts_path.exists()
        assert str(known_hosts_path) in command
        assert len(attempts) >= 2


def test_ensure_repo_checkout_relocates_inaccessible_path(
    app, owner, tenant, monkeypatch
):
    inaccessible_path = "/Users/eim/src/floads/github/aiops/instance/repos/demo"

    with app.app_context():
        project = Project(
            name="demo-project",
            repo_url="https://example.com/demo.git",
            default_branch="main",
            local_path=inaccessible_path,
            tenant=tenant,
            owner=owner,
        )
        db.session.add(project)
        db.session.commit()

        class DummyRepo:
            def __init__(self, repo_path: Path):
                self.path = Path(repo_path)
                self.git_dir = self.path / ".git"
                self.git = self

            @classmethod
            def clone_from(cls, repo_url, path, branch=None, env=None):
                path = Path(path)
                path.mkdir(parents=True, exist_ok=True)
                (path / ".git").mkdir(parents=True, exist_ok=True)
                return cls(path)

            def custom_environment(self, **kwargs):
                class _Ctx:
                    def __enter__(self_inner):
                        return self

                    def __exit__(self_inner, exc_type, exc, tb):
                        return False

                return _Ctx()

            def status(self, *args, **kwargs):
                return ""

        monkeypatch.setattr("app.services.git_service.Repo", DummyRepo)

        repo = ensure_repo_checkout(project)
        storage_root = Path(app.config["REPO_STORAGE_PATH"]).expanduser().resolve()
        new_path = Path(project.local_path).resolve()
        assert new_path == storage_root or storage_root in new_path.parents
        assert repo.path == Path(project.local_path)


def test_resolve_project_key_rebases_legacy_path(app, owner, tenant, tmp_path):
    with app.app_context():
        legacy_dir = Path(app.instance_path) / "keys"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_dir / "legacy-key.pem"
        legacy_file.write_text(
            """-----BEGIN OPENSSH PRIVATE KEY-----\nLEGACY\n-----END OPENSSH PRIVATE KEY-----\n""",
            encoding="utf-8",
        )

        project_key = SSHKey(
            name="legacy-key",
            public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQClegacy",
            fingerprint="legacy-fingerprint",
            user=owner,
            tenant=tenant,
            private_key_path="/previous/env/instance/keys/legacy-key.pem",
        )
        project = Project(
            name="legacy-project",
            repo_url="git@example.com/legacy.git",
            default_branch="main",
            local_path=str(tmp_path / "repos" / "legacy"),
            tenant=tenant,
            owner=owner,
            ssh_key=project_key,
        )
        db.session.add_all([project_key, project])
        db.session.commit()

        resolved = _resolve_project_ssh_key_path(project)
        assert resolved == str(legacy_file)


def _create_project(app, owner, tenant, local_path: Path) -> int:
    with app.app_context():
        project = Project(
            name=f"proj-{local_path.name}",
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(local_path),
            tenant=tenant,
            owner=owner,
        )
        db.session.add(project)
        db.session.commit()
        return project.id


def test_delete_project_branch_removes_branch(app, owner, tenant, tmp_path):
    repo_path = tmp_path / "repos" / "demo-delete"
    repo_path.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(repo_path)
    (repo_path / "README.md").write_text("root", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    repo.git.branch("-M", "main")
    repo.git.checkout("-b", "feature/demo")
    (repo_path / "demo.txt").write_text("demo", encoding="utf-8")
    repo.index.add(["demo.txt"])
    repo.index.commit("feature work")
    repo.git.checkout("main")

    project_id = _create_project(app, owner, tenant, repo_path)

    with app.app_context():
        project = Project.query.get(project_id)
        delete_project_branch(project, "feature/demo", force=True)
        remaining = [head.name for head in Repo(repo_path).heads]
        assert "feature/demo" not in remaining


def test_delete_project_branch_rejects_default(app, owner, tenant, tmp_path):
    repo_path = tmp_path / "repos" / "demo-delete-default"
    repo_path.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(repo_path)
    (repo_path / "README.md").write_text("root", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    repo.git.branch("-M", "main")

    project_id = _create_project(app, owner, tenant, repo_path)

    with app.app_context():
        project = Project.query.get(project_id)
        with pytest.raises(RuntimeError, match="Cannot delete the default branch"):
            delete_project_branch(project, "main")
