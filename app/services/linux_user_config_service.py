"""Service for managing Linux user mapping configuration.

Provides functions to load and save the Linux user mapping from/to the database
(SystemConfig table).
"""

from __future__ import annotations

from app.extensions import db
from app.models import SystemConfig

# Configuration key for Linux user mapping
LINUX_USER_MAPPING_KEY = "linux_user_mapping"


def load_linux_user_mapping() -> dict[str, str]:
    """Load Linux user mapping from the database.

    Returns:
        Dictionary mapping aiops user email to Linux username.
        Returns empty dict if not configured.
    """
    try:
        config = SystemConfig.query.filter_by(key=LINUX_USER_MAPPING_KEY).first()
        if config and config.value:
            return dict(config.value)
        return {}
    except Exception:
        # If database is not available or table doesn't exist, return empty dict
        return {}


def save_linux_user_mapping(mapping: dict[str, str]) -> None:
    """Save Linux user mapping to the database.

    Args:
        mapping: Dictionary mapping aiops user email to Linux username

    Raises:
        Exception: If database operation fails
    """
    try:
        config = SystemConfig.query.filter_by(key=LINUX_USER_MAPPING_KEY).first()

        if config:
            config.value = mapping
        else:
            config = SystemConfig(key=LINUX_USER_MAPPING_KEY, value=mapping)
            db.session.add(config)

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_linux_user_mapping() -> dict[str, str]:
    """Get the current Linux user mapping.

    Convenience function that calls load_linux_user_mapping.

    Returns:
        Dictionary mapping aiops user email to Linux username
    """
    return load_linux_user_mapping()
