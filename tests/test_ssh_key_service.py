"""Tests for SSH key encryption, decryption, and ssh-agent management."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

import pytest

from app.services.ssh_key_service import (
    SSHKeyServiceError,
    _add_key_to_agent,
    _get_encryption_key,
    _kill_ssh_agent,
    _start_ssh_agent,
    decrypt_private_key,
    encrypt_private_key,
    ssh_key_context,
)


# Sample test SSH key (not a real key, for testing only)
TEST_PRIVATE_KEY = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBGzKp7mYRj7YqK5XKxqJHXkQxXxKqXKxqJHXkQxXxKqXAAAAJgL9zqvC/c
6rwAAAALc3NoLWVkMjU1MTkAAAAgRsyqe5mEY+2KiuVysaiR15EMV8SqlysaiR15EMV8Sq
lwAAAEAVj7LXKxqJHXkQxXxKqXKxqJHXkQxXxKqXRsyqe5mEY+2KiuVysaiR15EMV8Sqlys
aiR15EMV8SqlwAAAADHRlc3Qta2V5AQIDBA==
-----END OPENSSH PRIVATE KEY-----
"""


@pytest.fixture
def mock_flask_app():
    """Create a mock Flask app with config."""
    from cryptography.fernet import Fernet

    app = Mock()
    # Generate a valid Fernet key for testing
    test_key = Fernet.generate_key().decode("utf-8")
    app.config = {
        "SSH_KEY_ENCRYPTION_KEY": test_key
    }
    app.logger = Mock()

    with patch("app.services.ssh_key_service.current_app", app):
        yield app


class TestEncryptionDecryption:
    """Test SSH key encryption and decryption."""

    def test_encrypt_private_key(self, mock_flask_app):
        """Test that private key encryption works."""
        encrypted = encrypt_private_key(TEST_PRIVATE_KEY)

        assert encrypted is not None
        assert isinstance(encrypted, bytes)
        assert encrypted != TEST_PRIVATE_KEY.encode("utf-8")
        assert len(encrypted) > 0

    def test_decrypt_private_key(self, mock_flask_app):
        """Test that private key decryption works."""
        encrypted = encrypt_private_key(TEST_PRIVATE_KEY)
        decrypted = decrypt_private_key(encrypted)

        assert decrypted == TEST_PRIVATE_KEY

    def test_encrypt_decrypt_roundtrip(self, mock_flask_app):
        """Test full encryption/decryption roundtrip."""
        original_key = TEST_PRIVATE_KEY
        encrypted_key = encrypt_private_key(original_key)
        decrypted_key = decrypt_private_key(encrypted_key)

        assert decrypted_key == original_key

    def test_encryption_key_from_config(self, mock_flask_app):
        """Test that encryption key is retrieved from Flask config."""
        key = _get_encryption_key()

        # Verify key is returned from config and is valid base64
        assert key is not None
        assert isinstance(key, bytes)
        assert len(key) > 0
        # Verify it's the same key from mock_flask_app config
        assert key.decode("utf-8") == mock_flask_app.config["SSH_KEY_ENCRYPTION_KEY"]

    def test_encryption_key_generation_when_missing(self):
        """Test that encryption key is generated when not in config."""
        app = Mock()
        app.config = {}
        app.logger = Mock()

        with patch("app.services.ssh_key_service.current_app", app):
            key = _get_encryption_key()

            assert key is not None
            assert isinstance(key, bytes)
            assert len(key) > 0
            # Should log a warning
            app.logger.warning.assert_called_once()

    def test_encrypt_empty_key_fails(self, mock_flask_app):
        """Test that encrypting empty string fails gracefully."""
        # Empty string should still encrypt, but it's not a valid SSH key
        encrypted = encrypt_private_key("")
        assert encrypted is not None

    def test_decrypt_invalid_data_fails(self, mock_flask_app):
        """Test that decrypting invalid data raises error."""
        with pytest.raises(SSHKeyServiceError):
            decrypt_private_key(b"invalid-encrypted-data")


class TestSSHAgent:
    """Test SSH agent management."""

    @patch("app.services.ssh_key_service.subprocess.run")
    def test_start_ssh_agent(self, mock_run):
        """Test starting ssh-agent."""
        mock_run.return_value = Mock(
            stdout="SSH_AUTH_SOCK=/tmp/ssh-agent.12345; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=12345; export SSH_AGENT_PID;\n",
            returncode=0,
        )

        auth_sock, agent_pid = _start_ssh_agent()

        assert auth_sock == "/tmp/ssh-agent.12345"
        assert agent_pid == 12345
        mock_run.assert_called_once()

    @patch("app.services.ssh_key_service.subprocess.run")
    def test_start_ssh_agent_failure(self, mock_run):
        """Test ssh-agent start failure."""
        mock_run.side_effect = subprocess.SubprocessError("Failed to start")

        with pytest.raises(SSHKeyServiceError):
            _start_ssh_agent()

    @patch("app.services.ssh_key_service.subprocess.run")
    @patch("app.services.ssh_key_service.tempfile.NamedTemporaryFile")
    @patch("app.services.ssh_key_service.os.chmod")
    @patch("app.services.ssh_key_service.os.unlink")
    def test_add_key_to_agent(self, mock_unlink, mock_chmod, mock_tempfile, mock_run):
        """Test adding key to ssh-agent."""
        # Mock temporary file
        mock_file = Mock()
        mock_file.name = "/tmp/test-key.key"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_tempfile.return_value = mock_file

        # Mock ssh-add success
        mock_run.return_value = Mock(returncode=0)

        _add_key_to_agent("/tmp/ssh-agent.12345", TEST_PRIVATE_KEY)

        # Verify file operations
        mock_file.write.assert_called_once_with(TEST_PRIVATE_KEY)
        mock_chmod.assert_called_once_with("/tmp/test-key.key", 0o600)

        # Verify ssh-add was called
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["ssh-add", "/tmp/test-key.key"]
        assert call_args[1]["env"]["SSH_AUTH_SOCK"] == "/tmp/ssh-agent.12345"

        # Verify cleanup
        mock_unlink.assert_called_once_with("/tmp/test-key.key")

    @patch("app.services.ssh_key_service.subprocess.run")
    @patch("app.services.ssh_key_service.tempfile.NamedTemporaryFile")
    @patch("app.services.ssh_key_service.os.chmod")
    @patch("app.services.ssh_key_service.os.unlink")
    def test_add_key_to_agent_failure(self, mock_unlink, mock_chmod, mock_tempfile, mock_run):
        """Test ssh-add failure."""
        # Mock temporary file
        mock_file = Mock()
        mock_file.name = "/tmp/test-key.key"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_tempfile.return_value = mock_file

        # Mock ssh-add failure
        mock_run.side_effect = subprocess.SubprocessError("Failed to add key")

        with pytest.raises(SSHKeyServiceError):
            _add_key_to_agent("/tmp/ssh-agent.12345", TEST_PRIVATE_KEY)

        # Verify cleanup still happens
        mock_unlink.assert_called_once_with("/tmp/test-key.key")

    @patch("app.services.ssh_key_service.subprocess.run")
    def test_kill_ssh_agent(self, mock_run):
        """Test killing ssh-agent."""
        mock_run.return_value = Mock(returncode=0)

        _kill_ssh_agent(12345)

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["kill", "12345"]

    @patch("app.services.ssh_key_service.subprocess.run")
    def test_kill_ssh_agent_failure(self, mock_run):
        """Test ssh-agent kill failure."""
        mock_run.side_effect = subprocess.SubprocessError("Failed to kill")

        with pytest.raises(SSHKeyServiceError):
            _kill_ssh_agent(12345)


class TestSSHKeyContext:
    """Test ssh_key_context context manager."""

    @patch("app.services.ssh_key_service._kill_ssh_agent")
    @patch("app.services.ssh_key_service._add_key_to_agent")
    @patch("app.services.ssh_key_service._start_ssh_agent")
    @patch("app.services.ssh_key_service.decrypt_private_key")
    def test_ssh_key_context_success(
        self, mock_decrypt, mock_start, mock_add, mock_kill, mock_flask_app
    ):
        """Test successful ssh_key_context usage."""
        # Setup mocks
        mock_decrypt.return_value = TEST_PRIVATE_KEY
        mock_start.return_value = ("/tmp/ssh-agent.12345", 12345)

        encrypted_key = encrypt_private_key(TEST_PRIVATE_KEY)

        with ssh_key_context(encrypted_key) as auth_sock:
            assert auth_sock == "/tmp/ssh-agent.12345"

            # Verify operations in correct order
            mock_decrypt.assert_called_once_with(encrypted_key)
            mock_start.assert_called_once()
            mock_add.assert_called_once_with("/tmp/ssh-agent.12345", TEST_PRIVATE_KEY)

        # Verify cleanup
        mock_kill.assert_called_once_with(12345)

    @patch("app.services.ssh_key_service._kill_ssh_agent")
    @patch("app.services.ssh_key_service._add_key_to_agent")
    @patch("app.services.ssh_key_service._start_ssh_agent")
    @patch("app.services.ssh_key_service.decrypt_private_key")
    def test_ssh_key_context_cleanup_on_exception(
        self, mock_decrypt, mock_start, mock_add, mock_kill, mock_flask_app
    ):
        """Test that ssh-agent is cleaned up even when exception occurs."""
        # Setup mocks
        mock_decrypt.return_value = TEST_PRIVATE_KEY
        mock_start.return_value = ("/tmp/ssh-agent.12345", 12345)
        mock_add.side_effect = SSHKeyServiceError("Failed to add key")

        encrypted_key = encrypt_private_key(TEST_PRIVATE_KEY)

        with pytest.raises(SSHKeyServiceError):
            with ssh_key_context(encrypted_key):
                pass  # Exception raised in _add_key_to_agent

        # Verify cleanup still happened
        mock_kill.assert_called_once_with(12345)

    @patch("app.services.ssh_key_service._kill_ssh_agent")
    @patch("app.services.ssh_key_service._add_key_to_agent")
    @patch("app.services.ssh_key_service._start_ssh_agent")
    @patch("app.services.ssh_key_service.decrypt_private_key")
    def test_ssh_key_context_cleanup_failure_logged(
        self, mock_decrypt, mock_start, mock_add, mock_kill, mock_flask_app
    ):
        """Test that cleanup failures are logged but don't raise."""
        # Setup mocks
        mock_decrypt.return_value = TEST_PRIVATE_KEY
        mock_start.return_value = ("/tmp/ssh-agent.12345", 12345)
        mock_kill.side_effect = SSHKeyServiceError("Failed to kill agent")

        encrypted_key = encrypt_private_key(TEST_PRIVATE_KEY)

        # Should not raise exception despite kill failure
        with ssh_key_context(encrypted_key) as auth_sock:
            assert auth_sock == "/tmp/ssh-agent.12345"

        # Verify cleanup was attempted
        mock_kill.assert_called_once_with(12345)
        # Verify warning was logged
        mock_flask_app.logger.warning.assert_called_once()
