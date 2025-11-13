from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from flask import current_app

CLAUDE_API_KEY_NAME = "api_key"


class ClaudeConfigError(RuntimeError):
    """Raised when Claude CLI credentials cannot be managed."""


def _safe_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        current_app.logger.debug("Unable to set permissions on %s", path)


def _cli_config_dir() -> Path:
    configured = current_app.config.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
    base_path = Path(configured).expanduser()
    base_path.mkdir(parents=True, exist_ok=True)
    _safe_chmod(base_path, 0o700)
    return base_path


def _cli_key_path() -> Path:
    return _cli_config_dir() / CLAUDE_API_KEY_NAME


def _storage_dir(user_id: int) -> Path:
    base = Path(current_app.instance_path) / "claude" / f"user-{user_id}"
    base.mkdir(parents=True, exist_ok=True)
    _safe_chmod(base, 0o700)
    return base


def _storage_key_path(user_id: int) -> Path:
    return _storage_dir(user_id) / CLAUDE_API_KEY_NAME


def _stored_payload(user_id: int) -> str:
    storage_path = _storage_key_path(user_id)
    if storage_path.exists():
        try:
            return storage_path.read_text(encoding="utf-8").strip()
        except OSError as exc:  # pragma: no cover - filesystem issue
            raise ClaudeConfigError(
                f"Failed to read Claude API key for user {user_id}: {exc}"
            ) from exc

    legacy_path = _cli_key_path()
    if legacy_path.exists():
        try:
            payload = legacy_path.read_text(encoding="utf-8").strip()
        except OSError as exc:  # pragma: no cover - filesystem issue
            raise ClaudeConfigError(
                "Failed to read legacy Claude API key: %s" % exc
            ) from exc
        storage_path.write_text(payload + "\n", encoding="utf-8")
        _safe_chmod(storage_path, 0o600)
        return payload

    return ""


def save_claude_api_key(raw_key: str, *, user_id: Optional[int] = None) -> None:
    if user_id is None:
        raise ClaudeConfigError("Select a user before saving Claude API credentials.")
    key = (raw_key or "").strip()
    if not key:
        raise ClaudeConfigError("Claude API key must not be empty.")
    storage_path = _storage_key_path(user_id)
    try:
        storage_path.write_text(key + "\n", encoding="utf-8")
        _safe_chmod(storage_path, 0o600)
    except OSError as exc:  # pragma: no cover - filesystem issue
        raise ClaudeConfigError(
            f"Failed to write Claude API key for user {user_id}: {exc}"
        ) from exc
    ensure_claude_api_key(user_id)


def load_claude_api_key(*, user_id: Optional[int] = None) -> str:
    if user_id is None:
        return ""
    return _stored_payload(user_id)


def ensure_claude_api_key(user_id: int) -> Tuple[Path, str]:
    payload = _stored_payload(user_id)
    if not payload:
        raise ClaudeConfigError("No Claude API key has been saved for this user yet.")
    cli_dir = _cli_config_dir()
    cli_path = _cli_key_path()
    try:
        cli_path.write_text(payload + "\n", encoding="utf-8")
        _safe_chmod(cli_path, 0o600)
    except OSError as exc:  # pragma: no cover
        raise ClaudeConfigError(
            f"Failed to prepare Claude CLI API key file: {exc}"
        ) from exc
    return cli_dir, payload


def get_user_api_paths(user_id: int) -> Tuple[Path, Path]:
    return _cli_key_path(), _storage_key_path(user_id)


__all__ = [
    "ClaudeConfigError",
    "save_claude_api_key",
    "load_claude_api_key",
    "ensure_claude_api_key",
    "get_user_api_paths",
]
