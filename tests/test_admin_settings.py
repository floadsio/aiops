from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import create_app, db
from app.config import Config
from app.models import User
from app.security import hash_password, verify_password


class SettingsTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(tmp_path: Path):
    class _Config(SettingsTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'settings.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        LOG_FILE = str(tmp_path / "logs" / "aiops.log")

    application = create_app(_Config, instance_path=tmp_path / "instance")
    with application.app_context():
        log_path = Path(application.config["LOG_FILE"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("Initial log line\n", encoding="utf-8")
        db.create_all()
        admin = User(
            email="admin@example.com",
            name="Admin",
            password_hash=hash_password("admin-pass"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login_admin(client):
    response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "admin-pass"},
        follow_redirects=True,
    )
    assert response.status_code == 200


def test_settings_page_loads(client, login_admin):
    resp = client.get("/admin/settings")
    assert resp.status_code == 200
    assert b"System Update" in resp.data
    assert b"User Accounts" in resp.data


def test_settings_update_branch_dropdown(client, login_admin, monkeypatch):
    monkeypatch.setattr(
        "app.services.branch_state.available_branches",
        lambda: ["git-identities", "main", "release-2024-08"],
    )
    monkeypatch.setattr("app.services.branch_state.load_recorded_branch", lambda: None)
    resp = client.get("/admin/settings")
    assert resp.status_code == 200
    assert b"git-identities" in resp.data
    assert b"release-2024-08" in resp.data
    assert b"Quick Branch Switch" in resp.data


def test_run_system_update_records_branch(app, client, login_admin, monkeypatch):
    marker_path = Path(app.instance_path) / "current_branch.txt"
    if marker_path.exists():
        marker_path.unlink()

    monkeypatch.setattr(
        "app.services.branch_state.available_branches",
        lambda: ["main", "release-2024-08"],
    )
    monkeypatch.setattr("app.services.branch_state.load_recorded_branch", lambda: None)

    def fake_run_update_script(*, extra_env=None):
        assert extra_env == {"AIOPS_UPDATE_BRANCH": "release-2024-08"}
        return SimpleNamespace(ok=True, returncode=0, stdout="done", stderr="")

    monkeypatch.setattr("app.routes.admin.run_update_script", fake_run_update_script)

    resp = client.post(
        "/admin/system/update",
        data={"branch": "release-2024-08", "submit": "Run Update"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert marker_path.exists()
    assert marker_path.read_text().strip() == "release-2024-08"


def test_quick_branch_switch_runs_update(app, client, login_admin, monkeypatch):
    called = {}

    def fake_run_update_script(*, extra_env=None):
        called["env"] = extra_env
        return SimpleNamespace(ok=True, returncode=0, stdout="done", stderr="")

    def fake_restart(command):
        called["restart"] = command
        return True, "Restart command executed."


    def fake_switch_repo_branch(branch):
        called["switch_repo_branch"] = branch

    monkeypatch.setattr("app.services.branch_state.available_branches", lambda: ["main", "develop"])
    monkeypatch.setattr("app.services.branch_state.load_recorded_branch", lambda: None)
    monkeypatch.setattr("app.routes.admin.switch_repo_branch", fake_switch_repo_branch)
    monkeypatch.setattr("app.routes.admin._trigger_restart", fake_restart)

    with app.app_context():
        app.config["UPDATE_RESTART_COMMAND"] = "systemctl restart aiops"

    resp = client.post(
        "/admin/system/quick-branch",
        data={"branch": "develop"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert called["switch_repo_branch"] == "develop"
    assert "restart" in called


def test_create_user_via_settings(app, client, login_admin):
    resp = client.post(
        "/admin/settings",
        data={
            "name": "Jane Operator",
            "email": "operator@example.com",
            "password": "strong-pass",
            "is_admin": "y",
            "submit": "Create User",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email="operator@example.com").first()
        assert user is not None
        assert user.is_admin is True


def test_update_user_details(app, client, login_admin):
    with app.app_context():
        user = User(
            email="member3@example.com",
            name="Member 3",
            password_hash=hash_password("member-pass"),
            is_admin=False,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    resp = client.post(
        f"/admin/settings/users/{user_id}/update",
        data={
            "user_id": str(user_id),
            "name": "Renamed User",
            "email": "renamed@example.com",
            "is_admin": "y",
            "submit": "Save Changes",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        updated = User.query.get(user_id)
        assert updated.name == "Renamed User"
        assert updated.email == "renamed@example.com"
        assert updated.is_admin is True


def test_update_user_rejects_duplicate_email(app, client, login_admin):
    with app.app_context():
        admin_email = User.query.filter_by(email="admin@example.com").one().email
        other = User(
            email="other@example.com",
            name="Other User",
            password_hash=hash_password("other-pass"),
            is_admin=False,
        )
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    resp = client.post(
        f"/admin/settings/users/{other_id}/update",
        data={
            "user_id": str(other_id),
            "name": "Other User",
            "email": admin_email,
            "submit": "Save Changes",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"A user with this email already exists." in resp.data
    with app.app_context():
        persisted = User.query.get(other_id)
        assert persisted.email == "other@example.com"


def test_update_user_prevents_last_admin_removal(app, client, login_admin):
    resp = client.post(
        "/admin/settings/users/1/update",
        data={
            "user_id": "1",
            "name": "Admin",
            "email": "admin@example.com",
            "submit": "Save Changes",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"At least one administrator must remain." in resp.data


def test_toggle_user_admin(app, client, login_admin):
    with app.app_context():
        user = User(
            email="member@example.com",
            name="Member",
            password_hash=hash_password("member-pass"),
            is_admin=False,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    resp = client.post(
        f"/admin/settings/users/{user_id}/toggle-admin",
        data={"user_id": str(user_id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert User.query.get(user_id).is_admin is True


def test_toggle_prevents_last_admin(client, login_admin):
    resp = client.post(
        "/admin/settings/users/1/toggle-admin",
        data={"user_id": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"At least one administrator must remain." in resp.data


def test_reset_user_password(app, client, login_admin):
    with app.app_context():
        user = User(
            email="member2@example.com",
            name="Member 2",
            password_hash=hash_password("member-pass"),
            is_admin=False,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        old_hash = user.password_hash

    resp = client.post(
        f"/admin/settings/users/{user_id}/reset-password",
        data={"user_id": str(user_id), "password": "fresh-secret"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        updated = User.query.get(user_id)
        assert updated.password_hash != old_hash
        assert verify_password(updated.password_hash, "fresh-secret")


def test_delete_user(app, client, login_admin):
    with app.app_context():
        user = User(
            email="temp@example.com",
            name="Temp",
            password_hash=hash_password("temp-pass"),
            is_admin=False,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    resp = client.post(
        f"/admin/settings/users/{user_id}/delete",
        data={"user_id": str(user_id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert User.query.get(user_id) is None


def test_fetch_logs(app, client, login_admin, tmp_path):
    log_path = Path(app.config["LOG_FILE"])
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")

    response = client.get("/admin/settings/logs?lines=2")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "line2" in payload["content"]
    assert "line1" not in payload["content"]
    assert payload["truncated"] is True
