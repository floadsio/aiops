from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

_DEFAULT_VERSION = "0.0.0-dev"


def _read_version_file() -> str | None:
    version_path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def get_version() -> str:
    env_version = os.getenv("AIOPS_VERSION")
    if env_version:
        return env_version.strip()

    try:
        return metadata.version("aiops")
    except metadata.PackageNotFoundError:
        pass
    except Exception:
        pass

    file_version = _read_version_file()
    if file_version:
        return file_version

    return _DEFAULT_VERSION


__version__ = get_version()


__all__ = ["get_version", "__version__"]
