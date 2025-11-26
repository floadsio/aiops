"""Tests for communications API endpoints."""

from __future__ import annotations

import secrets
from pathlib import Path

import bcrypt
import pytest

from app import create_app, db
from app.config import Config
from app.models import APIKey, Tenant, User
from app.security import hash_password


class CommunicationsTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app_and_key(tmp_path: Path):
    """Create test app with database and return both app and API key."""
    # Generate key before creating app
    api_key_str = f"aiops_{secrets.token_hex(16)}"
    key_hash = bcrypt.hashpw(api_key_str.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    key_prefix = api_key_str[:12]  # "aiops_" + first 6 hex chars

    class _Config(CommunicationsTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"

    application = create_app(_Config)

    with application.app_context():
        db.create_all()

        # Create test user
        user = User(
            email="test@example.com",
            name="Test User",
            password_hash=hash_password("password123"),
            is_admin=False,
        )
        tenant = Tenant(name="test-tenant", description="Test Tenant")
        db.session.add_all([user, tenant])
        db.session.commit()

        # Create API key for auth
        api_key = APIKey(
            user_id=user.id,
            name="test-key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=["read", "write"],
        )
        db.session.add(api_key)
        db.session.commit()

    return application, api_key_str


@pytest.fixture()
def app(app_and_key):
    """Extract app from app_and_key fixture."""
    return app_and_key[0]


@pytest.fixture()
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture()
def api_key_value(app_and_key):
    """Get API key string for authenticated requests."""
    return app_and_key[1]


@pytest.fixture()
def auth_headers(api_key_value):
    """Create auth headers with API key."""
    return {
        "Authorization": f"Bearer {api_key_value}",
        "Content-Type": "application/json",
    }


class TestCommunicationsAPI:
    """Test communications API endpoints."""

    def test_get_communications_empty(self, client, auth_headers):
        """Test GET /api/v1/communications with no issues."""
        response = client.get(
            "/api/v1/communications",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "communications" in data
        assert "pagination" in data
        assert data["communications"] == []
        assert data["pagination"]["total"] == 0

    def test_get_communication_threads_empty(self, client, auth_headers):
        """Test GET /api/v1/communications/threads with no issues."""
        response = client.get(
            "/api/v1/communications/threads",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "threads" in data
        assert "pagination" in data
        assert data["threads"] == []
        assert data["pagination"]["total"] == 0

    def test_get_communications_requires_auth(self, client):
        """Test that communications endpoint requires authentication."""
        response = client.get("/api/v1/communications")
        assert response.status_code == 401

    def test_get_communications_pagination(self, client, auth_headers):
        """Test pagination parameters."""
        response = client.get(
            "/api/v1/communications?limit=10&offset=0",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["pagination"]["limit"] == 10
        assert data["pagination"]["offset"] == 0

    def test_get_communications_max_limit(self, client, auth_headers):
        """Test that limit is capped at 500."""
        response = client.get(
            "/api/v1/communications?limit=1000",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["pagination"]["limit"] == 500
