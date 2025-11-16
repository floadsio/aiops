"""Configuration management for AIops CLI."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml


class Config:
    """CLI configuration manager."""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize configuration.

        Args:
            config_path: Path to config file (defaults to ~/.aiops/config.yaml)
        """
        if config_path is None:
            config_path = Path.home() / ".aiops" / "config.yaml"
        self.config_path = config_path
        self._config: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from file."""
        if self.config_path.exists():
            with open(self.config_path, encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {}

    def save(self) -> None:
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, default_flow_style=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        # Check environment variables first
        env_key = f"AIOPS_{key.upper()}"
        env_value = os.getenv(env_key)
        if env_value is not None:
            return env_value

        # Fall back to config file
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        self._config[key] = value
        self.save()

    def delete(self, key: str) -> None:
        """Delete configuration value.

        Args:
            key: Configuration key
        """
        if key in self._config:
            del self._config[key]
            self.save()

    def all(self) -> dict[str, Any]:
        """Get all configuration values.

        Returns:
            dict: All configuration
        """
        return self._config.copy()

    @property
    def url(self) -> Optional[str]:
        """Get API base URL."""
        return self.get("url")

    @property
    def api_key(self) -> Optional[str]:
        """Get API key."""
        return self.get("api_key")

    @property
    def output_format(self) -> str:
        """Get output format (table, json, yaml)."""
        return self.get("output_format", "table")
