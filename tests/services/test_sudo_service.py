"""Tests for sudo service utilities."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.services.sudo_service import (
    SudoError,
    SudoResult,
    chgrp,
    chmod,
    chown,
    mkdir,
    rm_rf,
    run_as_user,
    test_path,
)


class TestSudoResult:
    """Tests for SudoResult dataclass."""

    def test_success_property_true(self):
        """Test that success returns True when returncode is 0."""
        result = SudoResult(returncode=0, stdout="output", stderr="")
        assert result.success is True

    def test_success_property_false(self):
        """Test that success returns False when returncode is non-zero."""
        result = SudoResult(returncode=1, stdout="", stderr="error")
        assert result.success is False


class TestRunAsUser:
    """Tests for run_as_user function."""

    @patch("app.services.sudo_service.subprocess.run")
    def test_run_as_user_success(self, mock_run):
        """Test successful command execution."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="success", stderr=""
        )

        result = run_as_user("testuser", ["ls", "-la"])

        assert result.success
        assert result.stdout == "success"
        mock_run.assert_called_once_with(
            ["sudo", "-n", "-u", "testuser", "ls", "-la"],
            capture_output=True,
            text=True,
            timeout=30.0,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_run_as_user_with_env(self, mock_run):
        """Test command execution with environment variables."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        result = run_as_user(
            "testuser",
            ["git", "status"],
            env={"GIT_SSH_COMMAND": "ssh -i key"},
        )

        assert result.success
        mock_run.assert_called_once_with(
            [
                "sudo",
                "-n",
                "-u",
                "testuser",
                "env",
                "GIT_SSH_COMMAND=ssh -i key",
                "git",
                "status",
            ],
            capture_output=True,
            text=True,
            timeout=30.0,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_run_as_user_with_custom_timeout(self, mock_run):
        """Test command execution with custom timeout."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr=""
        )

        result = run_as_user("testuser", ["sleep", "1"], timeout=60.0)

        assert result.success
        mock_run.assert_called_once_with(
            ["sudo", "-n", "-u", "testuser", "sleep", "1"],
            capture_output=True,
            text=True,
            timeout=60.0,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_run_as_user_failure_with_check(self, mock_run):
        """Test command failure raises SudoError when check=True."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="permission denied"
        )

        with pytest.raises(SudoError) as exc_info:
            run_as_user("testuser", ["cat", "/root/secret"], check=True)

        assert "permission denied" in str(exc_info.value)

    @patch("app.services.sudo_service.subprocess.run")
    def test_run_as_user_failure_without_check(self, mock_run):
        """Test command failure returns result when check=False."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="permission denied"
        )

        result = run_as_user("testuser", ["cat", "/root/secret"], check=False)

        assert not result.success
        assert result.returncode == 1
        assert result.stderr == "permission denied"

    @patch("app.services.sudo_service.subprocess.run")
    def test_run_as_user_timeout(self, mock_run):
        """Test command timeout raises SudoError."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["sudo", "-n", "-u", "testuser", "sleep", "100"],
            timeout=5,
        )

        with pytest.raises(SudoError) as exc_info:
            run_as_user("testuser", ["sleep", "100"], timeout=5.0)

        assert "timed out" in str(exc_info.value).lower()

    @patch("app.services.sudo_service.subprocess.run")
    def test_run_as_user_command_not_found(self, mock_run):
        """Test command not found raises SudoError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(SudoError) as exc_info:
            run_as_user("testuser", ["nonexistent-command"])

        assert "not found" in str(exc_info.value).lower()


class TestTestPath:
    """Tests for test_path function."""

    @patch("app.services.sudo_service.run_as_user")
    def test_test_path_exists(self, mock_run_as_user):
        """Test checking for existing path."""
        mock_run_as_user.return_value = SudoResult(
            returncode=0, stdout="", stderr=""
        )

        result = test_path("testuser", "/home/testuser/file.txt")

        assert result is True
        mock_run_as_user.assert_called_once_with(
            "testuser",
            ["test", "-e", "/home/testuser/file.txt"],
            timeout=5.0,
            check=False,
        )

    @patch("app.services.sudo_service.run_as_user")
    def test_test_path_not_exists(self, mock_run_as_user):
        """Test checking for non-existing path."""
        mock_run_as_user.return_value = SudoResult(
            returncode=1, stdout="", stderr=""
        )

        result = test_path("testuser", "/home/testuser/nonexistent.txt")

        assert result is False

    @patch("app.services.sudo_service.run_as_user")
    def test_test_path_sudo_error(self, mock_run_as_user):
        """Test handling SudoError in test_path."""
        mock_run_as_user.side_effect = SudoError("sudo failed")

        result = test_path("testuser", "/some/path")

        assert result is False


class TestMkdir:
    """Tests for mkdir function."""

    @patch("app.services.sudo_service.run_as_user")
    def test_mkdir_with_parents(self, mock_run_as_user):
        """Test creating directory with parent directories."""
        mock_run_as_user.return_value = SudoResult(
            returncode=0, stdout="", stderr=""
        )

        mkdir("testuser", "/home/testuser/path/to/dir")

        mock_run_as_user.assert_called_once_with(
            "testuser",
            ["mkdir", "-p", "/home/testuser/path/to/dir"],
            timeout=10.0,
        )

    @patch("app.services.sudo_service.run_as_user")
    def test_mkdir_without_parents(self, mock_run_as_user):
        """Test creating directory without parent directories."""
        mock_run_as_user.return_value = SudoResult(
            returncode=0, stdout="", stderr=""
        )

        mkdir("testuser", "/home/testuser/dir", parents=False)

        mock_run_as_user.assert_called_once_with(
            "testuser",
            ["mkdir", "/home/testuser/dir"],
            timeout=10.0,
        )

    @patch("app.services.sudo_service.run_as_user")
    def test_mkdir_failure(self, mock_run_as_user):
        """Test mkdir failure raises SudoError."""
        mock_run_as_user.side_effect = SudoError("mkdir failed")

        with pytest.raises(SudoError):
            mkdir("testuser", "/home/testuser/dir")


class TestChown:
    """Tests for chown function."""

    @patch("app.services.sudo_service.subprocess.run")
    def test_chown_owner_only(self, mock_run):
        """Test changing only owner."""
        mock_run.return_value = MagicMock(returncode=0)

        chown("/path/to/file", owner="newowner")

        mock_run.assert_called_once_with(
            ["sudo", "chown", "newowner", "/path/to/file"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_chown_group_only(self, mock_run):
        """Test changing only group."""
        mock_run.return_value = MagicMock(returncode=0)

        chown("/path/to/file", group="newgroup")

        mock_run.assert_called_once_with(
            ["sudo", "chown", ":newgroup", "/path/to/file"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_chown_owner_and_group(self, mock_run):
        """Test changing both owner and group."""
        mock_run.return_value = MagicMock(returncode=0)

        chown("/path/to/file", owner="newowner", group="newgroup")

        mock_run.assert_called_once_with(
            ["sudo", "chown", "newowner:newgroup", "/path/to/file"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_chown_no_arguments(self):
        """Test chown with no owner or group raises ValueError."""
        with pytest.raises(ValueError):
            chown("/path/to/file")

    @patch("app.services.sudo_service.subprocess.run")
    def test_chown_failure(self, mock_run):
        """Test chown failure raises SudoError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["sudo", "chown"], stderr="operation failed"
        )

        with pytest.raises(SudoError) as exc_info:
            chown("/path/to/file", owner="newowner")

        assert "chown" in str(exc_info.value).lower()


class TestChmod:
    """Tests for chmod function."""

    @patch("app.services.sudo_service.subprocess.run")
    def test_chmod_success(self, mock_run):
        """Test successful chmod operation."""
        mock_run.return_value = MagicMock(returncode=0)

        chmod("/path/to/file", 0o755)

        mock_run.assert_called_once_with(
            ["sudo", "chmod", "755", "/path/to/file"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_chmod_with_setgid(self, mock_run):
        """Test chmod with setgid bit."""
        mock_run.return_value = MagicMock(returncode=0)

        chmod("/path/to/dir", 0o2775)

        mock_run.assert_called_once_with(
            ["sudo", "chmod", "2775", "/path/to/dir"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_chmod_failure(self, mock_run):
        """Test chmod failure raises SudoError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["sudo", "chmod"], stderr="operation failed"
        )

        with pytest.raises(SudoError) as exc_info:
            chmod("/path/to/file", 0o644)

        assert "chmod" in str(exc_info.value).lower()


class TestChgrp:
    """Tests for chgrp function."""

    @patch("app.services.sudo_service.subprocess.run")
    def test_chgrp_success(self, mock_run):
        """Test successful chgrp operation."""
        mock_run.return_value = MagicMock(returncode=0)

        chgrp("/path/to/file", "syseng")

        mock_run.assert_called_once_with(
            ["sudo", "chgrp", "syseng", "/path/to/file"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )

    @patch("app.services.sudo_service.subprocess.run")
    def test_chgrp_failure(self, mock_run):
        """Test chgrp failure raises SudoError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["sudo", "chgrp"], stderr="group not found"
        )

        with pytest.raises(SudoError) as exc_info:
            chgrp("/path/to/file", "nonexistent")

        assert "chgrp" in str(exc_info.value).lower()


class TestRmRf:
    """Tests for rm_rf function."""

    @patch("app.services.sudo_service.run_as_user")
    def test_rm_rf_success(self, mock_run_as_user):
        """Test successful recursive removal."""
        mock_run_as_user.return_value = SudoResult(
            returncode=0, stdout="", stderr=""
        )

        rm_rf("testuser", "/home/testuser/old_dir")

        mock_run_as_user.assert_called_once_with(
            "testuser",
            ["rm", "-rf", "/home/testuser/old_dir"],
            timeout=30.0,
        )

    @patch("app.services.sudo_service.run_as_user")
    def test_rm_rf_failure(self, mock_run_as_user):
        """Test rm_rf failure raises SudoError."""
        mock_run_as_user.side_effect = SudoError("rm failed")

        with pytest.raises(SudoError):
            rm_rf("testuser", "/home/testuser/dir")
