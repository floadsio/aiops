"""Tests for notification service."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestNotificationType:
    """Tests for NotificationType constants."""

    def test_all_types_include_categories(self):
        """Test that ALL_TYPES includes all category types."""
        from app.services.notification_service import NotificationType

        # Verify categories exist
        assert len(NotificationType.ISSUE_TYPES) > 0
        assert len(NotificationType.PROJECT_TYPES) > 0
        assert len(NotificationType.SYSTEM_TYPES) > 0
        assert len(NotificationType.SESSION_TYPES) > 0

        # Verify ALL_TYPES includes all
        expected_count = (
            len(NotificationType.ISSUE_TYPES) +
            len(NotificationType.PROJECT_TYPES) +
            len(NotificationType.SYSTEM_TYPES) +
            len(NotificationType.SESSION_TYPES)
        )
        assert len(NotificationType.ALL_TYPES) == expected_count


class TestNotificationPriority:
    """Tests for NotificationPriority constants."""

    def test_priority_values(self):
        """Test priority constant values."""
        from app.services.notification_service import NotificationPriority

        assert NotificationPriority.LOW == "low"
        assert NotificationPriority.NORMAL == "normal"
        assert NotificationPriority.HIGH == "high"
        assert NotificationPriority.CRITICAL == "critical"


class TestNotificationModel:
    """Tests for Notification model methods."""

    def test_notification_get_metadata_empty(self):
        """Test get_metadata returns empty dict when no metadata."""
        from app.models import Notification

        notification = Notification(
            user_id=1,
            notification_type="test.type",
            title="Test",
            created_at=datetime.utcnow(),
        )
        notification.metadata_json = None

        result = notification.get_metadata()
        assert result == {}

    def test_notification_get_metadata_valid(self):
        """Test get_metadata parses JSON correctly."""
        from app.models import Notification

        notification = Notification(
            user_id=1,
            notification_type="test.type",
            title="Test",
            created_at=datetime.utcnow(),
        )
        notification.metadata_json = '{"key": "value", "number": 123}'

        result = notification.get_metadata()
        assert result == {"key": "value", "number": 123}

    def test_notification_get_metadata_invalid_json(self):
        """Test get_metadata handles invalid JSON gracefully."""
        from app.models import Notification

        notification = Notification(
            user_id=1,
            notification_type="test.type",
            title="Test",
            created_at=datetime.utcnow(),
        )
        notification.metadata_json = "invalid json {"

        result = notification.get_metadata()
        assert result == {}

    def test_notification_set_metadata(self):
        """Test set_metadata serializes dict to JSON."""
        from app.models import Notification

        notification = Notification(
            user_id=1,
            notification_type="test.type",
            title="Test",
            created_at=datetime.utcnow(),
        )

        notification.set_metadata({"project": "aiops", "count": 5})
        assert notification.metadata_json == '{"project": "aiops", "count": 5}'

    def test_notification_set_metadata_none(self):
        """Test set_metadata handles None value."""
        from app.models import Notification

        notification = Notification(
            user_id=1,
            notification_type="test.type",
            title="Test",
            created_at=datetime.utcnow(),
        )

        notification.set_metadata(None)
        assert notification.metadata_json is None

    def test_notification_to_dict(self):
        """Test notification to_dict method."""
        from app.models import Notification

        now = datetime.utcnow()
        notification = Notification(
            id=1,
            user_id=1,
            notification_type="issue.assigned",
            title="Test Issue",
            message="Test message",
            priority="normal",
            is_read=False,
            resource_type="issue",
            resource_id=123,
            resource_url="/issues/123",
            created_at=now,
        )
        notification.metadata_json = '{"project": "test"}'

        result = notification.to_dict()

        assert result["id"] == 1
        assert result["type"] == "issue.assigned"
        assert result["title"] == "Test Issue"
        assert result["message"] == "Test message"
        assert result["priority"] == "normal"
        assert result["is_read"] is False
        assert result["resource_type"] == "issue"
        assert result["resource_id"] == 123
        assert result["resource_url"] == "/issues/123"
        assert result["metadata"]["project"] == "test"
        assert result["created_at"] is not None


class TestNotificationPreferencesModel:
    """Tests for NotificationPreferences model methods."""

    def test_enabled_types_property(self):
        """Test enabled_types property getter."""
        from app.models import NotificationPreferences

        prefs = NotificationPreferences(user_id=1)
        prefs.enabled_types_json = '["issue.assigned", "issue.mentioned"]'

        result = prefs.enabled_types
        assert result == ["issue.assigned", "issue.mentioned"]

    def test_enabled_types_property_empty(self):
        """Test enabled_types returns empty list when None."""
        from app.models import NotificationPreferences

        prefs = NotificationPreferences(user_id=1)
        prefs.enabled_types_json = None

        result = prefs.enabled_types
        assert result == []

    def test_enabled_types_setter(self):
        """Test enabled_types property setter."""
        from app.models import NotificationPreferences

        prefs = NotificationPreferences(user_id=1)
        prefs.enabled_types = ["issue.assigned", "issue.commented"]

        assert prefs.enabled_types_json == '["issue.assigned", "issue.commented"]'

    def test_muted_projects_property(self):
        """Test muted_projects property."""
        from app.models import NotificationPreferences

        prefs = NotificationPreferences(user_id=1)
        prefs.muted_projects_json = "[1, 2, 3]"

        result = prefs.muted_projects
        assert result == [1, 2, 3]

    def test_muted_projects_setter(self):
        """Test muted_projects setter."""
        from app.models import NotificationPreferences

        prefs = NotificationPreferences(user_id=1)
        prefs.muted_projects = [5, 6]

        assert prefs.muted_projects_json == "[5, 6]"

    def test_default_enabled_types(self):
        """Test DEFAULT_ENABLED_TYPES includes expected types."""
        from app.models import NotificationPreferences

        defaults = NotificationPreferences.DEFAULT_ENABLED_TYPES

        # Should include critical types
        assert "issue.assigned" in defaults
        assert "issue.mentioned" in defaults
        assert "issue.commented" in defaults
        assert "system.backup_failed" in defaults

        # Should NOT include noisy types
        assert "issue.created" not in defaults
        assert "system.backup_completed" not in defaults

    def test_to_dict(self):
        """Test preferences to_dict method."""
        from app.models import NotificationPreferences
        from datetime import datetime

        prefs = NotificationPreferences(
            id=1,
            user_id=1,
            email_notifications=False,
            email_frequency="realtime",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        prefs.enabled_types_json = '["issue.assigned"]'
        prefs.muted_projects_json = "[1]"
        prefs.muted_integrations_json = "[2]"

        result = prefs.to_dict()

        assert result["enabled_types"] == ["issue.assigned"]
        assert result["muted_projects"] == [1]
        assert result["muted_integrations"] == [2]
        assert result["email_notifications"] is False
        assert result["email_frequency"] == "realtime"


class TestNotificationGenerator:
    """Tests for notification generator functions."""

    def test_truncate_message_short(self):
        """Test _truncate_message with short text."""
        from app.services.notification_generator import _truncate_message

        result = _truncate_message("short text", 100)
        assert result == "short text"

    def test_truncate_message_long(self):
        """Test _truncate_message with long text."""
        from app.services.notification_generator import _truncate_message

        text = "a" * 100
        result = _truncate_message(text, 50)

        assert len(result) == 50
        assert result.endswith("...")

    def test_truncate_message_empty(self):
        """Test _truncate_message with empty text."""
        from app.services.notification_generator import _truncate_message

        result = _truncate_message("", 50)
        assert result == ""

        result = _truncate_message(None, 50)
        assert result == ""

    def test_extract_mentions_github(self):
        """Test _extract_mentions with GitHub format."""
        from app.services.notification_generator import _extract_mentions

        # Mock the resolve function to return None (no mapping)
        with patch("app.services.notification_generator.resolve_user_from_external_identity") as mock_resolve:
            mock_resolve.return_value = None

            result = _extract_mentions("Hey @testuser please review", "github")

            # Should have tried to resolve 'testuser'
            mock_resolve.assert_called_once_with("testuser", "github", None)
            assert result == []

    def test_extract_mentions_jira_accountid(self):
        """Test _extract_mentions with Jira account ID format."""
        from app.services.notification_generator import _extract_mentions

        with patch("app.services.notification_generator.resolve_user_from_external_identity") as mock_resolve:
            mock_resolve.return_value = None

            result = _extract_mentions("Hey [~accountid:abc123] please review", "jira")

            # Jira has multiple patterns so it may call multiple times
            # Just verify it was called and returned empty (no mappings)
            assert mock_resolve.called
            assert result == []

    def test_extract_mentions_empty(self):
        """Test _extract_mentions with no mentions."""
        from app.services.notification_generator import _extract_mentions

        result = _extract_mentions("No mentions here", "github")
        assert result == []

        result = _extract_mentions(None, "github")
        assert result == []
