"""AIops CLI - Command-line interface for AIops REST API."""

import os
from importlib import metadata
from pathlib import Path

_DEFAULT_VERSION = "0.0.0-dev"


def _read_version_file() -> str | None:
    """Read version from project root VERSION file."""
    # Try to find VERSION file relative to this package
    # Works for both installed and development installations
    version_path = Path(__file__).resolve().parent.parent.parent / "VERSION"
    try:
        value = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def get_version() -> str:
    """Get the CLI version from VERSION file or package metadata.

    Priority order:
    1. AIOPS_VERSION environment variable
    2. Installed package version
    3. Project VERSION file
    4. Default version
    """
    env_version = os.getenv("AIOPS_VERSION")
    if env_version:
        return env_version.strip()

    try:
        return metadata.version("aiops-cli")
    except metadata.PackageNotFoundError:
        pass
    except Exception:
        pass

    file_version = _read_version_file()
    if file_version:
        return file_version

    return _DEFAULT_VERSION


__version__ = get_version()
