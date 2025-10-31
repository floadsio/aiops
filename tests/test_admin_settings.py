from __future__ import annotations

from pathlib import Path

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

    application = create_app(_Config, instance_path=tmp_path / "instance")
    with application.app_context():
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
