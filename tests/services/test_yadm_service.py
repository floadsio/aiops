"""Unit tests for yadm_service module."""

import subprocess
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services import yadm_service


class TestYadmKeyEncryption:
    """Tests for YadmKeyEncryption encryption/decryption utilities."""

    @patch.dict("os.environ", {"SSH_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode()})
    def test_encrypt_gpg_key_success(self):
        """Test successful GPG key encryption."""
        test_key_data = b"-----BEGIN PGP PRIVATE KEY BLOCK-----\ntest"

        encrypted = yadm_service.YadmKeyEncryption.encrypt_gpg_key(test_key_data)

        assert isinstance(encrypted, bytes)
        assert encrypted != test_key_data
        assert len(encrypted) > 0

    @patch.dict("os.environ", {}, clear=True)
    def test_encrypt_gpg_key_missing_encryption_key(self):
        """Test encryption fails when SSH_KEY_ENCRYPTION_KEY is not set."""
        test_key_data = b"test_key_data"

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.YadmKeyEncryption.encrypt_gpg_key(test_key_data)

    @patch.dict("os.environ", {"SSH_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode()})
    def test_encrypt_decrypt_roundtrip(self):
        """Test that encrypted keys can be decrypted successfully."""
        test_key_data = b"-----BEGIN PGP PRIVATE KEY BLOCK-----\ntest private key\n-----END PGP PRIVATE KEY BLOCK-----"

        encrypted = yadm_service.YadmKeyEncryption.encrypt_gpg_key(test_key_data)
        decrypted = yadm_service.YadmKeyEncryption.decrypt_gpg_key(encrypted)

        assert decrypted == test_key_data

    def test_decrypt_gpg_key_invalid_data(self):
        """Test decryption fails with invalid encrypted data."""
        invalid_encrypted_data = b"invalid_encrypted_data"

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.YadmKeyEncryption.decrypt_gpg_key(invalid_encrypted_data)

    @patch.dict("os.environ", {}, clear=True)
    def test_decrypt_gpg_key_missing_encryption_key(self):
        """Test decryption fails when SSH_KEY_ENCRYPTION_KEY is not set."""
        encrypted_data = b"some_encrypted_data"

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.YadmKeyEncryption.decrypt_gpg_key(encrypted_data)


class TestStoreGpgKeyEncrypted:
    """Tests for store_gpg_key_encrypted function."""

    @patch.dict("os.environ", {"SSH_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode()})
    def test_store_gpg_key_encrypted_success(self):
        """Test successful GPG key storage in database."""
        mock_user = Mock()
        mock_user.email = "user@example.com"

        key_data = b"-----BEGIN PGP PRIVATE KEY BLOCK-----\ntest"
        key_id = "4F8B3C1A2D5E7F9A"

        yadm_service.store_gpg_key_encrypted(mock_user, key_data, key_id)

        assert mock_user.gpg_key_id == key_id
        assert mock_user.gpg_private_key_encrypted is not None
        assert isinstance(mock_user.gpg_private_key_encrypted, bytes)

    @patch.dict("os.environ", {}, clear=True)
    def test_store_gpg_key_encrypted_missing_key(self):
        """Test storage fails when encryption key is not configured."""
        mock_user = Mock()
        mock_user.email = "user@example.com"

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.store_gpg_key_encrypted(
                mock_user, b"test_key", "4F8B3C1A2D5E7F9A"
            )


class TestGetGpgKeyDecrypted:
    """Tests for get_gpg_key_decrypted function."""

    @patch.dict("os.environ", {"SSH_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode()})
    def test_get_gpg_key_decrypted_success(self):
        """Test successful GPG key retrieval and decryption."""
        key_data = b"-----BEGIN PGP PRIVATE KEY BLOCK-----\ntest"
        key_id = "4F8B3C1A2D5E7F9A"

        # First store the key
        mock_user = Mock()
        mock_user.email = "user@example.com"
        yadm_service.store_gpg_key_encrypted(mock_user, key_data, key_id)

        # Now retrieve it
        decrypted = yadm_service.get_gpg_key_decrypted(mock_user)

        assert decrypted == key_data

    def test_get_gpg_key_decrypted_not_configured(self):
        """Test retrieving key when not configured returns None."""
        mock_user = Mock()
        mock_user.gpg_private_key_encrypted = None
        mock_user.email = "user@example.com"

        result = yadm_service.get_gpg_key_decrypted(mock_user)

        assert result is None


class TestImportGpgKey:
    """Tests for import_gpg_key function."""

    @patch("app.services.yadm_service.subprocess.run")
    @patch("app.services.yadm_service.Path")
    def test_import_gpg_key_success(self, mock_path, mock_run):
        """Test successful GPG key import."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        mock_path_instance = Mock()
        mock_path.return_value = mock_path_instance

        key_data = b"test_key_data"
        yadm_service.import_gpg_key(
            "testuser", "/home/testuser", key_data, "4F8B3C1A2D5E7F9A"
        )

        # Verify subprocess was called with sudo
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "sudo" in call_args
        assert "testuser" in call_args
        assert "gpg" in call_args
        assert "--import" in call_args

    @patch("app.services.yadm_service.subprocess.run")
    @patch("app.services.yadm_service.Path")
    def test_import_gpg_key_failure(self, mock_path, mock_run):
        """Test GPG key import handles failures."""
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="gpg: error importing key"
        )
        mock_path_instance = Mock()
        mock_path.return_value = mock_path_instance

        key_data = b"test_key_data"

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.import_gpg_key(
                "testuser", "/home/testuser", key_data, "4F8B3C1A2D5E7F9A"
            )

    @patch("app.services.yadm_service.subprocess.run")
    @patch("app.services.yadm_service.Path")
    def test_import_gpg_key_timeout(self, mock_path, mock_run):
        """Test GPG key import handles timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("gpg", 30)
        mock_path_instance = Mock()
        mock_path.return_value = mock_path_instance

        key_data = b"test_key_data"

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.import_gpg_key(
                "testuser", "/home/testuser", key_data, "4F8B3C1A2D5E7F9A"
            )


class TestInitializeYadmRepo:
    """Tests for initialize_yadm_repo function."""

    @patch("app.services.yadm_service.subprocess.run")
    def test_initialize_yadm_repo_success(self, mock_run):
        """Test successful yadm repo initialization."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        yadm_service.initialize_yadm_repo(
            "testuser",
            "/home/testuser",
            "git@github.com:floads/dotfiles.git",
            "main",
        )

        # Verify subprocess was called with correct command
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "sudo" in call_args
        assert "testuser" in call_args
        assert "yadm" in call_args
        assert "clone" in call_args
        assert "--bootstrap" in call_args
        assert "git@github.com:floads/dotfiles.git" in call_args
        assert "main" in call_args

    @patch("app.services.yadm_service.subprocess.run")
    def test_initialize_yadm_repo_failure(self, mock_run):
        """Test yadm repo initialization handles clone failure."""
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="fatal: repository not found"
        )

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.initialize_yadm_repo(
                "testuser",
                "/home/testuser",
                "git@github.com:invalid/repo.git",
                "main",
            )

    @patch("app.services.yadm_service.subprocess.run")
    def test_initialize_yadm_repo_timeout(self, mock_run):
        """Test yadm repo initialization handles timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("yadm", 300)

        with pytest.raises(yadm_service.YadmServiceError):
            yadm_service.initialize_yadm_repo(
                "testuser",
                "/home/testuser",
                "git@github.com:floads/dotfiles.git",
                "main",
            )


class TestApplyYadmBootstrap:
    """Tests for apply_yadm_bootstrap function."""

    @patch("app.services.yadm_service.subprocess.run")
    def test_apply_yadm_bootstrap_success(self, mock_run):
        """Test successful yadm bootstrap execution."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        yadm_service.apply_yadm_bootstrap("testuser", "/home/testuser")

        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "sudo" in call_args
        assert "testuser" in call_args
        assert "yadm" in call_args
        assert "bootstrap" in call_args

    @patch("app.services.yadm_service.subprocess.run")
    def test_apply_yadm_bootstrap_non_zero_exit(self, mock_run):
        """Test bootstrap doesn't fail on non-zero exit (non-critical errors)."""
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="some warning"
        )

        # Should not raise exception for non-critical bootstrap issues
        yadm_service.apply_yadm_bootstrap("testuser", "/home/testuser")

        assert mock_run.called


class TestYadmDecrypt:
    """Tests for yadm_decrypt function."""

    @patch("app.services.yadm_service.subprocess.run")
    def test_yadm_decrypt_success(self, mock_run):
        """Test successful yadm file decryption."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        yadm_service.yadm_decrypt("testuser", "/home/testuser")

        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "sudo" in call_args
        assert "testuser" in call_args
        assert "yadm" in call_args
        assert "decrypt" in call_args

    @patch("app.services.yadm_service.subprocess.run")
    def test_yadm_decrypt_no_encrypted_files(self, mock_run):
        """Test decrypt handles case where no encrypted files exist."""
        mock_run.return_value = Mock(
            returncode=1, stderr="Nothing to decrypt"
        )

        # Should not raise exception for missing encrypted files
        yadm_service.yadm_decrypt("testuser", "/home/testuser")

        assert mock_run.called

    @patch("app.services.yadm_service._find_yadm_dir")
    @patch("app.services.yadm_service.subprocess.run")
    def test_yadm_decrypt_passphrase_uses_stdin(self, mock_run, mock_find_dir):
        """Test that yadm_decrypt passes passphrase via stdin, not cli args."""
        # Mock custom yadm directory detection
        mock_find_dir.return_value = (
            "/home/testuser/.config/yadm",
            "/home/testuser/.local/share/yadm"
        )
        # Regular yadm call succeeds
        mock_run.return_value = Mock(
            returncode=0, stdout="", stderr=""
        )

        passphrase = "test_password_123"
        yadm_service.yadm_decrypt(
            "testuser", "/home/testuser", passphrase=passphrase
        )

        # Verify subprocess.run was called
        assert mock_run.called
        # Get the yadm decrypt call (second call after _find_yadm_dir)
        calls = [c for c in mock_run.call_args_list]
        # Should have been called with yadm decrypt
        assert any("yadm" in str(c) and "decrypt" in str(c) for c in calls)

        # Check the passphrase was passed via stdin (input parameter)
        # not on the command line
        for c in calls:
            cmd_args = c[0][0] if c[0] else []
            # Passphrase should NOT be in command arguments
            assert not any("test_password_123" in str(arg) for arg in cmd_args)
            # But it should be passed via input parameter (stdin)
            if "input" in c[1]:
                assert "test_password_123" in c[1]["input"]


class TestVerifyYadmSetup:
    """Tests for verify_yadm_setup function."""

    @patch("app.services.yadm_service.subprocess.run")
    def test_verify_yadm_setup_success(self, mock_run):
        """Test successful yadm setup verification."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        with patch("pathlib.Path.exists", return_value=True):
            result = yadm_service.verify_yadm_setup("testuser", "/home/testuser")

        assert result is True

    @patch("app.services.yadm_service.subprocess.run")
    def test_verify_yadm_setup_missing_directory(self, mock_run):
        """Test verification fails when .yadm directory doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = yadm_service.verify_yadm_setup("testuser", "/home/testuser")

        assert result is False

    @patch("app.services.yadm_service.subprocess.run")
    def test_verify_yadm_setup_status_failure(self, mock_run):
        """Test verification fails when yadm status returns error."""
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="error")

        with patch("pathlib.Path.exists", return_value=True):
            result = yadm_service.verify_yadm_setup("testuser", "/home/testuser")

        assert result is False


class TestCheckYadmInstalled:
    """Tests for check_yadm_installed function."""

    @patch("app.services.yadm_service.subprocess.run")
    def test_check_yadm_installed_true(self, mock_run):
        """Test yadm is detected as installed."""
        mock_run.return_value = Mock(returncode=0, stdout="/usr/bin/yadm")

        result = yadm_service.check_yadm_installed()

        assert result is True

    @patch("app.services.yadm_service.subprocess.run")
    def test_check_yadm_installed_false(self, mock_run):
        """Test yadm is detected as not installed."""
        mock_run.return_value = Mock(returncode=1, stdout="")

        result = yadm_service.check_yadm_installed()

        assert result is False

    @patch("app.services.yadm_service.subprocess.run")
    def test_check_yadm_installed_exception(self, mock_run):
        """Test exception handling when checking for yadm."""
        mock_run.side_effect = Exception("error checking yadm")

        result = yadm_service.check_yadm_installed()

        assert result is False


class TestYadmServiceError:
    """Tests for YadmServiceError exception."""

    def test_yadm_service_error_is_exception(self):
        """Test YadmServiceError is an Exception subclass."""
        exc = yadm_service.YadmServiceError("test error")
        assert isinstance(exc, Exception)
        assert str(exc) == "test error"
