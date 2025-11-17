"""Tests for Linux user switching service."""

from unittest.mock import MagicMock

from app.services.linux_users import (
    get_linux_user_for_aiops_user,
    get_linux_user_info,
    get_user_home_directory,
    resolve_linux_username,
    should_use_login_shell,
    validate_linux_user_exists,
)


class TestGetLinuxUserInfo:
    """Tests for get_linux_user_info function."""

    def test_get_user_info_success(self):
        """Test successful retrieval of user information."""
        # Get info for root user (always exists on Unix)
        user_info = get_linux_user_info("root")
        assert user_info is not None
        assert user_info.username == "root"
        assert user_info.uid == 0
        assert isinstance(user_info.gid, int)
        assert isinstance(user_info.home, str)
        assert isinstance(user_info.shell, str)

    def test_get_user_info_nonexistent(self):
        """Test retrieval of nonexistent user."""
        user_info = get_linux_user_info("nonexistent_user_xyz_12345")
        assert user_info is None


class TestResolveLinuxUsername:
    """Tests for resolve_linux_username function."""

    def test_resolve_with_mapping_strategy_email(self, tmp_path):
        """Test username resolution using email with mapping strategy."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"user@example.com": "example-user"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "user@example.com"

            result = resolve_linux_username(user)
            assert result == "ivo"

    def test_resolve_with_mapping_strategy_username(self, tmp_path):
        """Test username resolution using username with mapping strategy."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"michael": "michael"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "michael@example.com"
            user.username = "michael"

            result = resolve_linux_username(user)
            assert result == "michael"

    def test_resolve_with_direct_strategy(self, tmp_path):
        """Test username resolution using direct strategy."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "direct"

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.username = "testuser"

            result = resolve_linux_username(user)
            assert result == "testuser"

    def test_resolve_with_direct_strategy_no_username(self, tmp_path):
        """Test direct strategy when username is not set."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "direct"

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock(spec=[])  # No attributes

            result = resolve_linux_username(user)
            assert result is None

    def test_resolve_with_mapping_not_found(self, tmp_path):
        """Test mapping strategy when user not in mapping."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"other@example.com": "other"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "unknown@example.com"
            user.username = "unknown"

            result = resolve_linux_username(user)
            assert result is None

    def test_resolve_with_mapping_fallback_to_name(self, tmp_path):
        """Test mapping strategy fallback to user name."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"John Doe": "john"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "john@example.com"
            user.username = None
            user.name = "John Doe"

            result = resolve_linux_username(user)
            assert result == "john"


class TestGetLinuxUserForAiopsUser:
    """Tests for get_linux_user_for_aiops_user function."""

    def test_get_user_info_success(self, tmp_path):
        """Test successful retrieval of Linux user for aiops user."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"root@example.com": "root"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "root@example.com"

            result = get_linux_user_for_aiops_user(user)
            assert result is not None
            assert result.username == "root"
            assert result.uid == 0

    def test_get_user_info_not_found_mapping(self, tmp_path):
        """Test when aiops user maps to nonexistent Linux user."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"fake@example.com": "nonexistent_user_xyz"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "fake@example.com"

            result = get_linux_user_for_aiops_user(user)
            assert result is None

    def test_get_user_info_no_mapping(self, tmp_path):
        """Test when aiops user has no mapping."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "unknown@example.com"

            result = get_linux_user_for_aiops_user(user)
            assert result is None


class TestGetUserHomeDirectory:
    """Tests for get_user_home_directory function."""

    def test_get_home_directory_success(self, tmp_path):
        """Test successful home directory retrieval."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"root@example.com": "root"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "root@example.com"

            result = get_user_home_directory(user)
            assert result == "/root"

    def test_get_home_directory_not_found(self, tmp_path):
        """Test home directory when user not found."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = None
            user.email = "unknown@example.com"

            result = get_user_home_directory(user)
            assert result is None

    def test_resolve_with_per_user_linux_username(self, tmp_path):
        """Test per-user linux_username takes precedence over mapping."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            LINUX_USER_STRATEGY = "mapping"
            LINUX_USER_MAPPING = {"user@example.com": "other"}

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            user = MagicMock()
            user.linux_username = "custom_user"
            user.email = "user@example.com"

            # Should return the per-user setting, not the global mapping
            result = resolve_linux_username(user)
            assert result == "custom_user"


class TestValidateLinuxUserExists:
    """Tests for validate_linux_user_exists function."""

    def test_validate_existing_user(self):
        """Test validation of existing user."""
        result = validate_linux_user_exists("root")
        assert result is True

    def test_validate_nonexistent_user(self):
        """Test validation of nonexistent user."""
        result = validate_linux_user_exists("nonexistent_user_xyz_12345")
        assert result is False


class TestShouldUseLoginShell:
    """Tests for should_use_login_shell function."""

    def test_default_use_login_shell(self, tmp_path):
        """Test default login shell setting."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            # Default should be True
            result = should_use_login_shell()
            assert result is True

    def test_use_login_shell_true(self, tmp_path):
        """Test login shell when explicitly set to True."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            USE_LOGIN_SHELL = True

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            result = should_use_login_shell()
            assert result is True

    def test_use_login_shell_false(self, tmp_path):
        """Test login shell when explicitly set to False."""
        from app import create_app
        from app.config import Config

        class TestConfig(Config):
            TESTING = True
            USE_LOGIN_SHELL = False

        app = create_app(TestConfig, instance_path=tmp_path / "instance")

        with app.app_context():
            result = should_use_login_shell()
            assert result is False
