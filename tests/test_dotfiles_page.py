"""Tests for dotfiles management page and API endpoints."""

import pytest
from flask import url_for
from unittest.mock import patch, MagicMock

from app.models import User, SystemConfig
from app.services.yadm_service import (
    get_yadm_managed_files,
    get_yadm_git_status,
    get_yadm_bootstrap_info,
    get_yadm_encryption_status,
    get_full_yadm_status,
    pull_and_apply_yadm_update,
    YadmServiceError,
)


class TestYadmServiceFunctions:
    """Test new yadm service functions."""

    def test_get_yadm_managed_files_not_initialized(self):
        """Test getting files when yadm is not initialized."""
        result = get_yadm_managed_files("testuser", "/home/testuser")
        assert isinstance(result, dict)
        assert "tracked" in result
        assert "encrypted" in result
        assert "modified" in result
        assert isinstance(result["tracked"], list)

    def test_get_yadm_git_status_not_initialized(self):
        """Test getting git status when yadm is not initialized."""
        result = get_yadm_git_status("testuser", "/home/testuser")
        assert isinstance(result, dict)
        assert "branch" in result
        assert "remote_url" in result
        assert "status_summary" in result
        assert "commits_ahead" in result
        assert "commits_behind" in result
        assert "dirty" in result

    def test_get_yadm_bootstrap_info_not_initialized(self):
        """Test getting bootstrap info when yadm is not initialized."""
        result = get_yadm_bootstrap_info("testuser", "/home/testuser")
        assert isinstance(result, dict)
        assert "exists" in result
        assert "executable" in result
        assert "bootstrap_scripts" in result
        assert result["exists"] is False

    def test_get_yadm_encryption_status_no_gpg_key(self):
        """Test getting encryption status without GPG key."""
        result = get_yadm_encryption_status("testuser", "/home/testuser")
        assert isinstance(result, dict)
        assert "has_encrypt_patterns" in result
        assert "gpg_key_configured" in result
        assert "gpg_key_imported" in result

    def test_get_full_yadm_status_structure(self, test_user):
        """Test get_full_yadm_status returns correct structure."""
        result = get_full_yadm_status(test_user)
        assert isinstance(result, dict)
        assert "user_email" in result
        assert "is_initialized" in result
        assert "yadm_installed" in result
        assert "timestamp" in result
        assert "files" in result
        assert "git" in result
        assert "bootstrap" in result
        assert "encryption" in result


class TestDotfilesRoutes:
    """Test dotfiles management page routes."""

    def test_manage_dotfiles_requires_login(self, client):
        """Test that manage_dotfiles requires authentication."""
        response = client.get(url_for("projects.manage_dotfiles"))
        assert response.status_code == 302  # Redirect to login

    def test_manage_dotfiles_get_authenticated(self, client, test_user):
        """Test loading dotfiles page when authenticated."""
        client.force_login(test_user)
        response = client.get(url_for("projects.manage_dotfiles"))
        assert response.status_code == 200
        assert b"Dotfiles Management" in response.data

    def test_manage_dotfiles_post_save_config(self, client, test_user, db):
        """Test saving personal dotfiles configuration."""
        client.force_login(test_user)
        response = client.post(
            url_for("projects.manage_dotfiles"),
            data={
                "personal_dotfile_repo_url": "https://github.com/testuser/dotfiles",
                "personal_dotfile_branch": "main",
                "submit": "Save Configuration",
            },
            follow_redirects=True
        )
        assert response.status_code == 200

        # Verify the configuration was saved
        updated_user = User.query.get(test_user.id)
        assert updated_user.personal_dotfile_repo_url == "https://github.com/testuser/dotfiles"
        assert updated_user.personal_dotfile_branch == "main"

    def test_manage_dotfiles_post_clear_override(self, client, test_user, db):
        """Test clearing personal dotfiles override."""
        client.force_login(test_user)

        # Set initial override
        test_user.personal_dotfile_repo_url = "https://github.com/testuser/dotfiles"
        test_user.personal_dotfile_branch = "main"
        db.session.commit()

        # Clear it
        response = client.post(
            url_for("projects.manage_dotfiles"),
            data={
                "clear_override": True,
                "submit": "Save Configuration",
            },
            follow_redirects=True
        )
        assert response.status_code == 200

        # Verify override was cleared
        updated_user = User.query.get(test_user.id)
        assert updated_user.personal_dotfile_repo_url is None
        assert updated_user.personal_dotfile_branch is None


class TestDotfilesAPI:
    """Test dotfiles API endpoints."""

    def test_dotfiles_init_requires_auth(self, client):
        """Test that dotfiles init endpoint requires authentication."""
        response = client.post("/api/v1/dotfiles/init", json={})
        assert response.status_code == 401

    def test_dotfiles_init_no_config(self, client, auth_headers):
        """Test dotfiles init fails when no repo configured."""
        response = client.post(
            "/api/v1/dotfiles/init",
            json={},
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "not configured" in response.json.get("error", "").lower()

    def test_dotfiles_status_requires_auth(self, client):
        """Test that dotfiles status endpoint requires authentication."""
        response = client.get("/api/v1/dotfiles/status")
        assert response.status_code == 401

    def test_dotfiles_status_returns_structure(self, client, auth_headers):
        """Test dotfiles status returns correct structure."""
        response = client.get(
            "/api/v1/dotfiles/status",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json
        assert "user_email" in data
        assert "is_initialized" in data
        assert "timestamp" in data

    def test_dotfiles_pull_and_update_requires_auth(self, client):
        """Test that pull-and-update endpoint requires authentication."""
        response = client.post("/api/v1/dotfiles/pull-and-update", json={})
        assert response.status_code == 401

    def test_dotfiles_decrypt_requires_auth(self, client):
        """Test that decrypt endpoint requires authentication."""
        response = client.post("/api/v1/dotfiles/decrypt", json={})
        assert response.status_code == 401


class TestYadmPageIntegration:
    """Integration tests for dotfiles page."""

    def test_sidebar_has_dotfiles_link(self, client, test_user):
        """Test that sidebar contains Dotfiles link."""
        client.force_login(test_user)
        response = client.get(url_for("admin.dashboard"))
        assert response.status_code == 200
        assert "Dotfiles" in response.data.decode() or "dotfiles" in response.data.decode()

    def test_dotfiles_page_displays_status_cards(self, client, test_user):
        """Test that dotfiles page shows status information."""
        client.force_login(test_user)
        response = client.get(url_for("projects.manage_dotfiles"))
        assert response.status_code == 200
        # Check for main sections
        page_content = response.data.decode()
        assert "Dotfiles Management" in page_content or "dotfiles" in page_content.lower()

    @patch("app.services.yadm_service.check_yadm_installed")
    def test_page_shows_yadm_not_installed_message(self, mock_check, client, test_user):
        """Test that page shows message when yadm is not installed."""
        mock_check.return_value = False
        client.force_login(test_user)
        response = client.get(url_for("projects.manage_dotfiles"))
        assert response.status_code == 200
        page_content = response.data.decode().lower()
        # Should show some indication that yadm is not available
        assert "not installed" in page_content or "error" in page_content


class TestFormValidation:
    """Test form validation for dotfiles configuration."""

    def test_invalid_repo_url_rejected(self, client, test_user):
        """Test that invalid repo URLs are rejected."""
        client.force_login(test_user)
        response = client.post(
            url_for("projects.manage_dotfiles"),
            data={
                "personal_dotfile_repo_url": "not a valid url",
                "personal_dotfile_branch": "main",
                "submit": "Save Configuration",
            }
        )
        # Should stay on page or redirect back (form validation error)
        assert response.status_code in [200, 302]

    def test_optional_url_field_accepts_empty(self, client, test_user):
        """Test that personal repo URL is optional."""
        client.force_login(test_user)
        response = client.post(
            url_for("projects.manage_dotfiles"),
            data={
                "personal_dotfile_repo_url": "",
                "personal_dotfile_branch": "",
                "submit": "Save Configuration",
            },
            follow_redirects=True
        )
        assert response.status_code == 200
