"""Tests for CLI git services (gh and glab integration)."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.services import cli_git_service, gh_service, glab_service


@pytest.fixture
def mock_github_project():
    """Create a mock project with GitHub integration."""
    project = Mock()
    project.id = 1
    project.repo_url = "https://github.com/owner/repo.git"
    project.default_branch = "main"

    integration = Mock()
    integration.id = 7
    integration.provider = "github"
    integration.api_token = "ghp_test_token_123"
    integration.base_url = None  # github.com

    project.integration = integration
    project.issue_integrations = []

    return project


@pytest.fixture
def mock_gitlab_project():
    """Create a mock project with GitLab integration."""
    project = Mock()
    project.id = 2
    project.repo_url = "https://gitlab.com/group/project.git"
    project.default_branch = "main"

    integration = Mock()
    integration.id = 8
    integration.provider = "gitlab"
    integration.api_token = "glpat_test_token_456"
    integration.base_url = None  # gitlab.com

    project.integration = integration
    project.issue_integrations = []

    return project


@pytest.fixture
def mock_github_enterprise_project():
    """Create a mock project with GitHub Enterprise integration."""
    project = Mock()
    project.id = 3
    project.repo_url = "https://github.example.com/owner/repo.git"
    project.default_branch = "main"

    integration = Mock()
    integration.id = 9
    integration.provider = "github"
    integration.api_token = "ghp_enterprise_token"
    integration.base_url = "https://github.example.com"

    project.integration = integration
    project.issue_integrations = []

    return project


@pytest.fixture
def mock_private_gitlab_project():
    """Create a mock project with private GitLab integration."""
    project = Mock()
    project.id = 4
    project.repo_url = "https://gitlab.example.com/group/project.git"
    project.default_branch = "main"

    integration = Mock()
    integration.id = 10
    integration.provider = "gitlab"
    integration.api_token = "glpat_private_token"
    integration.base_url = "https://gitlab.example.com"

    project.integration = integration
    project.issue_integrations = []

    return project


class TestCliGitServiceRouting:
    """Test the unified CLI git service routing."""

    def test_supports_cli_git_github(self, mock_github_project):
        """Test that GitHub projects with PAT support CLI git."""
        assert cli_git_service.supports_cli_git(mock_github_project) is True

    def test_supports_cli_git_gitlab(self, mock_gitlab_project):
        """Test that GitLab projects with PAT support CLI git."""
        assert cli_git_service.supports_cli_git(mock_gitlab_project) is True

    def test_supports_cli_git_no_integration(self):
        """Test that projects without integration don't support CLI git."""
        project = Mock()
        project.integration = None

        assert cli_git_service.supports_cli_git(project) is False

    def test_supports_cli_git_no_token(self, mock_github_project):
        """Test that projects without PAT don't support CLI git."""
        mock_github_project.integration.api_token = None
        mock_github_project.integration.access_token = None

        assert cli_git_service.supports_cli_git(mock_github_project) is False


class TestGitHubService:
    """Test GitHub CLI (gh) service."""

    def test_get_project_integration_success(self, mock_github_project):
        """Test getting GitHub integration from project."""
        integration = gh_service._get_project_integration(mock_github_project)

        assert integration is not None
        assert integration.provider == "github"

    def test_get_project_integration_wrong_provider(self, mock_gitlab_project):
        """Test that GitLab integration is rejected."""
        integration = gh_service._get_project_integration(mock_gitlab_project)

        assert integration is None

    def test_get_github_url_public(self, mock_github_project):
        """Test getting URL for github.com (should return None)."""
        integration = mock_github_project.integration
        url = gh_service._get_github_url(mock_github_project, integration)

        assert url is None  # github.com is default

    def test_get_github_url_enterprise(self, mock_github_enterprise_project):
        """Test getting URL for GitHub Enterprise."""
        integration = mock_github_enterprise_project.integration
        url = gh_service._get_github_url(mock_github_enterprise_project, integration)

        assert url == "https://github.example.com"

    def test_get_github_token(self, mock_github_project):
        """Test getting GitHub PAT token."""
        integration = mock_github_project.integration
        token = gh_service._get_github_token(mock_github_project, integration)

        assert token == "ghp_test_token_123"

    @patch('app.services.gh_service.subprocess.run')
    def test_clone_repo_github(self, mock_run, mock_github_project, tmp_path):
        """Test cloning a GitHub repository."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        target_path = tmp_path / "test-repo"

        gh_service.clone_repo(mock_github_project, target_path)

        # Verify gh command was called
        assert mock_run.called
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "gh"
        assert "repo" in call_args[0][0]
        assert "clone" in call_args[0][0]

        # Verify environment has GH_TOKEN
        env = call_args[1].get("env", {})
        assert "GH_TOKEN" in env
        assert env["GH_TOKEN"] == "ghp_test_token_123"

    @patch('app.services.gh_service.subprocess.run')
    def test_clone_repo_enterprise(self, mock_run, mock_github_enterprise_project, tmp_path):
        """Test cloning from GitHub Enterprise with GH_HOST."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        target_path = tmp_path / "test-repo"

        gh_service.clone_repo(mock_github_enterprise_project, target_path)

        # Verify GH_HOST is set for Enterprise
        call_args = mock_run.call_args
        env = call_args[1].get("env", {})
        assert "GH_HOST" in env
        assert env["GH_HOST"] == "https://github.example.com"

    @patch('app.services.gh_service.subprocess.run')
    def test_pull_repo(self, mock_run, mock_github_project, tmp_path):
        """Test pulling latest changes from GitHub."""
        mock_run.return_value = Mock(returncode=0, stdout="Already up to date.", stderr="")
        repo_path = tmp_path / "existing-repo"
        repo_path.mkdir()

        result = gh_service.pull_repo(mock_github_project, repo_path)

        assert "up to date" in result.lower()
        assert mock_run.called

        # Verify git pull command
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "git"
        assert call_args[0][0][1] == "pull"

    @patch('app.services.gh_service.subprocess.run')
    def test_push_repo(self, mock_run, mock_github_project, tmp_path):
        """Test pushing changes to GitHub."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="To github.com:owner/repo.git")
        repo_path = tmp_path / "existing-repo"
        repo_path.mkdir()

        result = gh_service.push_repo(mock_github_project, repo_path)

        assert "github.com" in result.lower()
        assert mock_run.called


class TestGitLabService:
    """Test GitLab CLI (glab) service."""

    def test_get_project_integration_success(self, mock_gitlab_project):
        """Test getting GitLab integration from project."""
        integration = glab_service._get_project_integration(mock_gitlab_project)

        assert integration is not None
        assert integration.provider == "gitlab"

    def test_get_project_integration_wrong_provider(self, mock_github_project):
        """Test that GitHub integration is rejected."""
        integration = glab_service._get_project_integration(mock_github_project)

        assert integration is None

    def test_get_gitlab_url_public(self, mock_gitlab_project):
        """Test getting URL for gitlab.com (should return None)."""
        integration = mock_gitlab_project.integration
        url = glab_service._get_gitlab_url(mock_gitlab_project, integration)

        assert url is None  # gitlab.com is default

    def test_get_gitlab_url_private(self, mock_private_gitlab_project):
        """Test getting URL for private GitLab instance."""
        integration = mock_private_gitlab_project.integration
        url = glab_service._get_gitlab_url(mock_private_gitlab_project, integration)

        assert url == "https://gitlab.example.com"

    def test_get_gitlab_token(self, mock_gitlab_project):
        """Test getting GitLab PAT token."""
        integration = mock_gitlab_project.integration
        token = glab_service._get_gitlab_token(mock_gitlab_project, integration)

        assert token == "glpat_test_token_456"

    @patch('app.services.glab_service.subprocess.run')
    def test_clone_repo_gitlab(self, mock_run, mock_gitlab_project, tmp_path):
        """Test cloning a GitLab repository."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        target_path = tmp_path / "test-repo"

        glab_service.clone_repo(mock_gitlab_project, target_path)

        # Verify glab command was called
        assert mock_run.called
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "glab"
        assert "repo" in call_args[0][0]
        assert "clone" in call_args[0][0]

        # Verify environment has GITLAB_TOKEN
        env = call_args[1].get("env", {})
        assert "GITLAB_TOKEN" in env
        assert env["GITLAB_TOKEN"] == "glpat_test_token_456"

    @patch('app.services.glab_service.subprocess.run')
    def test_clone_repo_private_instance(self, mock_run, mock_private_gitlab_project, tmp_path):
        """Test cloning from private GitLab with GITLAB_HOST."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        target_path = tmp_path / "test-repo"

        glab_service.clone_repo(mock_private_gitlab_project, target_path)

        # Verify GITLAB_HOST is set for private instance
        call_args = mock_run.call_args
        env = call_args[1].get("env", {})
        assert "GITLAB_HOST" in env
        assert env["GITLAB_HOST"] == "https://gitlab.example.com"

    @patch('app.services.glab_service.subprocess.run')
    def test_pull_repo(self, mock_run, mock_gitlab_project, tmp_path):
        """Test pulling latest changes from GitLab."""
        mock_run.return_value = Mock(returncode=0, stdout="Already up to date.", stderr="")
        repo_path = tmp_path / "existing-repo"
        repo_path.mkdir()

        result = glab_service.pull_repo(mock_gitlab_project, repo_path)

        assert "up to date" in result.lower()
        assert mock_run.called

    @patch('app.services.glab_service.subprocess.run')
    def test_push_repo(self, mock_run, mock_gitlab_project, tmp_path):
        """Test pushing changes to GitLab."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="To gitlab.com:group/project.git")
        repo_path = tmp_path / "existing-repo"
        repo_path.mkdir()

        result = glab_service.push_repo(mock_gitlab_project, repo_path)

        assert "gitlab.com" in result.lower()
        assert mock_run.called


class TestProjectOverrides:
    """Test per-project URL and token overrides."""

    def test_github_project_override_url(self, mock_github_project):
        """Test project-level URL override for GitHub Enterprise."""
        # Add project override
        override = Mock()
        override.integration_id = 7
        override.override_base_url = "https://github.custom.com"
        override.override_api_token = None
        mock_github_project.issue_integrations = [override]

        integration = mock_github_project.integration
        url = gh_service._get_github_url(mock_github_project, integration)

        assert url == "https://github.custom.com"

    def test_github_project_override_token(self, mock_github_project):
        """Test project-level token override for GitHub."""
        # Add project override
        override = Mock()
        override.integration_id = 7
        override.override_api_token = "ghp_project_specific_token"
        override.override_base_url = None
        mock_github_project.issue_integrations = [override]

        integration = mock_github_project.integration
        token = gh_service._get_github_token(mock_github_project, integration)

        assert token == "ghp_project_specific_token"

    def test_gitlab_project_override_url(self, mock_gitlab_project):
        """Test project-level URL override for private GitLab."""
        # Add project override
        override = Mock()
        override.integration_id = 8
        override.override_base_url = "https://gitlab.custom.com"
        override.override_api_token = None
        mock_gitlab_project.issue_integrations = [override]

        integration = mock_gitlab_project.integration
        url = glab_service._get_gitlab_url(mock_gitlab_project, integration)

        assert url == "https://gitlab.custom.com"

    def test_gitlab_project_override_token(self, mock_gitlab_project):
        """Test project-level token override for GitLab."""
        # Add project override
        override = Mock()
        override.integration_id = 8
        override.override_api_token = "glpat_project_specific_token"
        override.override_base_url = None
        mock_gitlab_project.issue_integrations = [override]

        integration = mock_gitlab_project.integration
        token = glab_service._get_gitlab_token(mock_gitlab_project, integration)

        assert token == "glpat_project_specific_token"
