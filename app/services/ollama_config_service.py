"""Service for managing Ollama configuration.

Provides functions to load and save Ollama endpoint configuration from/to the database
(SystemConfig table).
"""

from __future__ import annotations

from typing import Any

from app.extensions import db
from app.models import SystemConfig

# Configuration key for Ollama settings
OLLAMA_CONFIG_KEY = "ollama_config"

# Default configuration
DEFAULT_OLLAMA_CONFIG = {
    "default_endpoint": "http://10.10.99.15:11434",
    "endpoints": {
        "default": "http://10.10.99.15:11434",
    },
    "default_model": "llama3.2",
    "timeout": 120,
    "api_key": "ollama",
}


def load_ollama_config() -> dict[str, Any]:
    """Load Ollama configuration from the database.

    Returns:
        Dictionary containing Ollama configuration.
        Returns default config if not configured.
    """
    try:
        config = SystemConfig.query.filter_by(key=OLLAMA_CONFIG_KEY).first()
        if config and config.value:
            return dict(config.value)
        return DEFAULT_OLLAMA_CONFIG.copy()
    except Exception:
        # If database is not available or table doesn't exist, return default
        return DEFAULT_OLLAMA_CONFIG.copy()


def save_ollama_config(config: dict[str, Any]) -> None:
    """Save Ollama configuration to the database.

    Args:
        config: Dictionary containing Ollama configuration

    Raises:
        Exception: If database operation fails
    """
    try:
        db_config = SystemConfig.query.filter_by(key=OLLAMA_CONFIG_KEY).first()

        if db_config:
            db_config.value = config
        else:
            db_config = SystemConfig(key=OLLAMA_CONFIG_KEY, value=config)
            db.session.add(db_config)

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_ollama_config() -> dict[str, Any]:
    """Get the current Ollama configuration.

    Convenience function that calls load_ollama_config.

    Returns:
        Dictionary containing Ollama configuration
    """
    return load_ollama_config()


def get_ollama_endpoint(name: str = "default") -> str:
    """Get a specific Ollama endpoint URL by name.

    Args:
        name: Name of the endpoint (defaults to "default")

    Returns:
        Endpoint URL string, or default endpoint if not found
    """
    config = load_ollama_config()
    endpoints = config.get("endpoints", {})
    return endpoints.get(name, config.get("default_endpoint", "http://localhost:11434"))


def add_ollama_endpoint(name: str, url: str) -> None:
    """Add or update an Ollama endpoint.

    Args:
        name: Name of the endpoint
        url: Endpoint URL

    Raises:
        Exception: If database operation fails
    """
    config = load_ollama_config()
    if "endpoints" not in config:
        config["endpoints"] = {}
    config["endpoints"][name] = url
    save_ollama_config(config)


def remove_ollama_endpoint(name: str) -> bool:
    """Remove an Ollama endpoint.

    Args:
        name: Name of the endpoint to remove

    Returns:
        True if endpoint was removed, False if it didn't exist

    Raises:
        Exception: If database operation fails
    """
    config = load_ollama_config()
    endpoints = config.get("endpoints", {})
    if name in endpoints:
        del endpoints[name]
        config["endpoints"] = endpoints
        save_ollama_config(config)
        return True
    return False


def set_default_endpoint(name: str) -> None:
    """Set the default Ollama endpoint.

    Args:
        name: Name of the endpoint to set as default

    Raises:
        ValueError: If endpoint name doesn't exist
        Exception: If database operation fails
    """
    config = load_ollama_config()
    endpoints = config.get("endpoints", {})

    if name not in endpoints:
        raise ValueError(f"Endpoint '{name}' does not exist")

    config["default_endpoint"] = endpoints[name]
    save_ollama_config(config)


def get_default_endpoint() -> str:
    """Get the default Ollama endpoint URL.

    Returns:
        Default endpoint URL string
    """
    config = load_ollama_config()
    return config.get("default_endpoint", "http://localhost:11434")


def set_default_model(model: str) -> None:
    """Set the default Ollama model.

    Args:
        model: Model name (e.g., "llama3.2", "codellama")

    Raises:
        Exception: If database operation fails
    """
    config = load_ollama_config()
    config["default_model"] = model
    save_ollama_config(config)


def get_default_model() -> str:
    """Get the default Ollama model.

    Returns:
        Default model name
    """
    config = load_ollama_config()
    return config.get("default_model", "llama3.2")


def set_api_key(api_key: str) -> None:
    """Set the Ollama API key.

    Args:
        api_key: API key for authentication

    Raises:
        Exception: If database operation fails
    """
    config = load_ollama_config()
    config["api_key"] = api_key
    save_ollama_config(config)


def get_api_key() -> str:
    """Get the Ollama API key.

    Returns:
        API key string
    """
    config = load_ollama_config()
    return config.get("api_key", "ollama")


def test_ollama_connection(
    endpoint: str | None = None, api_key: str | None = None
) -> dict[str, Any]:
    """Test connection to an Ollama endpoint.

    Args:
        endpoint: Endpoint URL to test (uses default if None)
        api_key: API key to use (uses configured key if None)

    Returns:
        Dictionary with test results:
            - success: bool
            - message: str
            - models: list (if successful)
            - error: str (if failed)
    """
    import requests

    config = load_ollama_config()
    test_endpoint = endpoint or config.get("default_endpoint", "http://localhost:11434")
    test_api_key = api_key or config.get("api_key", "ollama")
    timeout = config.get("timeout", 120)

    try:
        # Test 1: Check if server is reachable
        tags_url = f"{test_endpoint.rstrip('/')}/api/tags"
        headers = {"Authorization": f"Bearer {test_api_key}"}

        response = requests.get(tags_url, headers=headers, timeout=min(timeout, 10))

        if response.status_code == 200:
            data = response.json()
            models = [model.get("name", "unknown") for model in data.get("models", [])]
            return {
                "success": True,
                "message": f"Connected successfully to {test_endpoint}",
                "models": models,
                "model_count": len(models),
            }
        elif response.status_code == 401:
            return {
                "success": False,
                "message": "Authentication failed",
                "error": "Invalid API key",
            }
        else:
            return {
                "success": False,
                "message": f"Server returned status {response.status_code}",
                "error": response.text[:200] if response.text else "No error details",
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "Connection timed out",
            "error": f"Server did not respond within {timeout} seconds",
        }
    except requests.exceptions.ConnectionError as exc:
        return {
            "success": False,
            "message": "Connection failed",
            "error": f"Could not connect to {test_endpoint}: {str(exc)[:100]}",
        }
    except Exception as exc:
        return {
            "success": False,
            "message": "Test failed",
            "error": str(exc)[:200],
        }
