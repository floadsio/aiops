"""Integration tests for sudo operations.

These tests actually execute sudo commands and should only run when:
1. The test user has sudo privileges configured
2. Running in a development/test environment

Skip these tests in CI unless CI is configured with proper sudo access.
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.sudo_service import (  # noqa: E402
    SudoError,
    chgrp,
    chmod,
    mkdir,
    rm_rf,
    run_as_user,
    test_path as sudo_test_path,
)

# Skip all tests in this module if not running as a user with sudo access
pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 and os.system("sudo -n true 2>/dev/null") != 0,
    reason="Requires passwordless sudo access",
)


@pytest.fixture
def test_username():
    """Get the current user's username for testing."""
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


@pytest.fixture
def temp_test_dir(test_username, tmp_path):
    """Create a temporary directory for testing sudo operations."""
    # Create a test directory that we can safely manipulate
    test_dir = tmp_path / "sudo_test"
    test_dir.mkdir(parents=True, exist_ok=True)

    # Make it accessible
    test_dir.chmod(0o755)

    yield test_dir

    # Cleanup - remove test directory
    try:
        rm_rf(test_username, str(test_dir))
    except SudoError:
        pass  # Best effort cleanup


class TestRunAsUserIntegration:
    """Integration tests for run_as_user function."""

    def test_run_simple_command(self, test_username):
        """Test running a simple command as the current user."""
        result = run_as_user(test_username, ["echo", "hello"])

        assert result.success
        assert "hello" in result.stdout

    def test_run_command_with_env(self, test_username):
        """Test running a command with environment variables."""
        result = run_as_user(
            test_username,
            ["sh", "-c", "echo $TEST_VAR"],
            env={"TEST_VAR": "test_value"},
        )

        assert result.success
        assert "test_value" in result.stdout

    def test_run_command_failure(self, test_username):
        """Test handling command failure."""
        with pytest.raises(SudoError) as exc_info:
            run_as_user(test_username, ["false"])

        assert "failed" in str(exc_info.value).lower()

    def test_run_command_timeout(self, test_username):
        """Test command timeout handling."""
        with pytest.raises(SudoError) as exc_info:
            run_as_user(test_username, ["sleep", "10"], timeout=0.5)

        assert "timed out" in str(exc_info.value).lower()


class TestPathOperations:
    """Integration tests for path operation functions."""

    def test_test_path_exists(self, test_username, temp_test_dir):
        """Test checking for existing path."""
        test_file = temp_test_dir / "test_file.txt"
        test_file.write_text("test content")

        assert sudo_test_path(test_username, str(test_file))

    def test_test_path_not_exists(self, test_username, temp_test_dir):
        """Test checking for non-existing path."""
        nonexistent = temp_test_dir / "nonexistent.txt"

        assert not sudo_test_path(test_username, str(nonexistent))

    def test_mkdir_creates_directory(self, test_username, temp_test_dir):
        """Test directory creation."""
        new_dir = temp_test_dir / "new_directory"

        mkdir(test_username, str(new_dir))

        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_mkdir_with_parents(self, test_username, temp_test_dir):
        """Test directory creation with parent directories."""
        nested_dir = temp_test_dir / "parent" / "child" / "grandchild"

        mkdir(test_username, str(nested_dir), parents=True)

        assert nested_dir.exists()
        assert nested_dir.is_dir()

    def test_rm_rf_removes_directory(self, test_username, temp_test_dir):
        """Test recursive directory removal."""
        dir_to_remove = temp_test_dir / "remove_me"
        dir_to_remove.mkdir()
        (dir_to_remove / "file.txt").write_text("content")

        rm_rf(test_username, str(dir_to_remove))

        assert not dir_to_remove.exists()


class TestPermissionOperations:
    """Integration tests for permission operation functions."""

    def test_chmod_changes_permissions(self, test_username, temp_test_dir):
        """Test changing file permissions."""
        test_file = temp_test_dir / "chmod_test.txt"
        test_file.write_text("test")

        chmod(str(test_file), 0o600)

        stat_result = test_file.stat()
        assert stat_result.st_mode & 0o777 == 0o600

    def test_chgrp_changes_group(self, test_username, temp_test_dir):
        """Test changing file group."""
        import grp

        test_file = temp_test_dir / "chgrp_test.txt"
        test_file.write_text("test")

        # Get current user's primary group
        current_gid = os.getgid()
        group_name = grp.getgrgid(current_gid).gr_name

        chgrp(str(test_file), group_name)

        stat_result = test_file.stat()
        assert stat_result.st_gid == current_gid


class TestWorkspaceSimulation:
    """Integration tests simulating workspace operations."""

    def test_simulate_workspace_initialization(self, test_username, temp_test_dir):
        """Simulate workspace initialization workflow."""
        workspace_path = temp_test_dir / "simulated_workspace"

        # Create workspace directory
        mkdir(test_username, str(workspace_path))
        assert workspace_path.exists()

        # Verify we can check if it exists via sudo
        assert sudo_test_path(test_username, str(workspace_path))

        # Create a .git directory to simulate initialized workspace
        git_dir = workspace_path / ".git"
        mkdir(test_username, str(git_dir))
        assert sudo_test_path(test_username, str(git_dir))

        # Cleanup
        rm_rf(test_username, str(workspace_path))
        assert not workspace_path.exists()

    def test_simulate_failed_clone_cleanup(self, test_username, temp_test_dir):
        """Simulate cleanup after failed git clone."""
        workspace_path = temp_test_dir / "failed_workspace"

        # Create workspace directory
        mkdir(test_username, str(workspace_path))

        # Simulate clone failure (no .git directory created)
        assert sudo_test_path(test_username, str(workspace_path))
        assert not sudo_test_path(test_username, str(workspace_path / ".git"))

        # Cleanup should remove the directory
        if sudo_test_path(test_username, str(workspace_path)):
            rm_rf(test_username, str(workspace_path))

        assert not workspace_path.exists()


class TestErrorConditions:
    """Integration tests for error conditions."""

    def test_mkdir_on_existing_directory(self, test_username, temp_test_dir):
        """Test mkdir on existing directory (should not fail with -p)."""
        existing_dir = temp_test_dir / "existing"
        existing_dir.mkdir()

        # Should not raise error
        mkdir(test_username, str(existing_dir))

        assert existing_dir.exists()

    def test_rm_rf_on_nonexistent_path(self, test_username, temp_test_dir):
        """Test rm_rf on non-existent path (should not fail)."""
        nonexistent = temp_test_dir / "does_not_exist"

        # rm -rf doesn't fail on non-existent paths
        rm_rf(test_username, str(nonexistent))

        # Should complete without error
        assert not nonexistent.exists()

    def test_chmod_on_nonexistent_file(self, temp_test_dir):
        """Test chmod on non-existent file (should fail)."""
        nonexistent = temp_test_dir / "nonexistent.txt"

        with pytest.raises(SudoError):
            chmod(str(nonexistent), 0o644)
