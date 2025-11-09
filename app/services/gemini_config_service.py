from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple

from flask import current_app


class GeminiConfigError(RuntimeError):
    """Raised when Gemini CLI configuration cannot be updated."""


def _safe_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        current_app.logger.debug("Unable to set permissions on %s", path)


def _base_config_dir() -> Path:
    configured = current_app.config.get("GEMINI_CONFIG_DIR")
    base_path = Path(configured).expanduser()
    base_path.mkdir(parents=True, exist_ok=True)
    _safe_chmod(base_path, 0o700)
    return base_path


def _cli_user_dir(user_id: Optional[int]) -> Path:
    if user_id is None:
        raise GeminiConfigError("User identifier is required for Gemini credentials.")
    base = _base_config_dir()
    suffix = f"user-{user_id}"
    if base.name == suffix:
        user_dir = base
    else:
        user_dir = base / suffix
    user_dir.mkdir(parents=True, exist_ok=True)
    _safe_chmod(user_dir, 0o700)
    return user_dir


def get_config_dir(user_id: Optional[int] = None) -> Path:
    """Return the config directory aiops should point GEMINI_CONFIG_DIR to."""
    if user_id is None:
        return _base_config_dir()
    return _cli_user_dir(user_id)


def _storage_dir(user_id: Optional[int]) -> Path:
    if user_id is None:
        raise GeminiConfigError("User identifier is required for Gemini credential storage.")
    base = Path(current_app.instance_path) / "gemini"
    base.mkdir(parents=True, exist_ok=True)
    _safe_chmod(base, 0o700)
    user_dir = base / f"user-{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    _safe_chmod(user_dir, 0o700)
    return user_dir


def _store_payload(name: str, payload: str, *, user_id: int) -> None:
    directory = _storage_dir(user_id)
    destination = directory / name
    try:
        destination.write_text(payload.strip() + "\n", encoding="utf-8")
        _safe_chmod(destination, 0o600)
    except OSError as exc:  # pragma: no cover - filesystem error path
        raise GeminiConfigError(f"Failed to persist {destination}: {exc}") from exc


def _write_cli_file(name: str, payload: str, user_id: int) -> None:
    directory = _cli_user_dir(user_id)
    destination = directory / name
    try:
        destination.write_text(payload.strip() + "\n", encoding="utf-8")
        _safe_chmod(destination, 0o600)
    except OSError as exc:  # pragma: no cover - filesystem error path
        raise GeminiConfigError(f"Failed to write {destination}: {exc}") from exc


def save_google_accounts(raw_json: str, *, user_id: Optional[int] = None) -> None:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise GeminiConfigError(f"google_accounts.json is not valid JSON: {exc}") from exc
    formatted = json.dumps(parsed, indent=2)
    if user_id is None:
        raise GeminiConfigError("User identifier is required when saving Gemini accounts.")
    _store_payload("google_accounts.json", formatted, user_id=user_id)
    ensure_user_config(user_id)


def save_oauth_creds(raw_json: str, *, user_id: Optional[int] = None) -> None:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise GeminiConfigError(f"oauth_creds.json is not valid JSON: {exc}") from exc
    formatted = json.dumps(parsed, indent=2)
    if user_id is None:
        raise GeminiConfigError("User identifier is required when saving Gemini OAuth credentials.")
    _store_payload("oauth_creds.json", formatted, user_id=user_id)
    ensure_user_config(user_id)


def _stored_payload(name: str, user_id: Optional[int]) -> str:
    if user_id is None:
        return ""
    directory = Path(current_app.instance_path) / "gemini" / f"user-{user_id}"
    destination = directory / name
    if destination.exists():
        try:
            return destination.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            raise GeminiConfigError(f"Failed to read persisted {destination}: {exc}") from exc

    # Legacy fallback: ~/.gemini/user-<id>/<name>
    legacy_dir = _base_config_dir() / f"user-{user_id}"
    legacy_file = legacy_dir / name
    if legacy_file.exists():
        try:
            contents = legacy_file.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            raise GeminiConfigError(f"Failed to read legacy {legacy_file}: {exc}") from exc
        directory.mkdir(parents=True, exist_ok=True)
        _safe_chmod(directory, 0o700)
        destination.write_text(contents, encoding="utf-8")
        _safe_chmod(destination, 0o600)
        return contents

    return ""


def _load_from_cli_dir(name: str, user_id: Optional[int]) -> str:
    if user_id is None:
        return ""
    cli_dir = _cli_user_dir(user_id)
    cli_file = cli_dir / name
    if not cli_file.exists():
        return ""
    try:
        contents = cli_file.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        raise GeminiConfigError(f"Failed to read CLI file {cli_file}: {exc}") from exc
    _store_payload(name, contents, user_id=user_id)
    return contents


def load_google_accounts(*, user_id: Optional[int] = None) -> str:
    stored = _stored_payload("google_accounts.json", user_id)
    if stored:
        return stored
    return _load_from_cli_dir("google_accounts.json", user_id)


def load_oauth_creds(*, user_id: Optional[int] = None) -> str:
    stored = _stored_payload("oauth_creds.json", user_id)
    if stored:
        return stored
    return _load_from_cli_dir("oauth_creds.json", user_id)


def ensure_user_config(user_id: int) -> Path:
    """Ensure a user's Gemini config dir contains required files, seeding from stored data."""
    if user_id is None:
        raise GeminiConfigError("User identifier is required for Gemini credentials.")
    user_dir = _cli_user_dir(user_id)
    for name in ("google_accounts.json", "oauth_creds.json"):
        payload = _stored_payload(name, user_id)
        if not payload:
            continue
        _write_cli_file(name, payload, user_id)
    return user_dir


def _ensure_payload_file(name: str, user_id: int) -> Optional[Path]:
    directory = _storage_dir(user_id)
    destination = directory / name
    if destination.exists():
        return destination
    _stored_payload(name, user_id)
    return destination if destination.exists() else None


def get_user_payload_paths(user_id: int) -> Tuple[Optional[Path], Optional[Path]]:
    accounts_path = _ensure_payload_file("google_accounts.json", user_id)
    oauth_path = _ensure_payload_file("oauth_creds.json", user_id)
    return accounts_path, oauth_path


__all__ = [
    "save_google_accounts",
    "save_oauth_creds",
    "load_google_accounts",
    "load_oauth_creds",
    "get_config_dir",
    "ensure_user_config",
    "GeminiConfigError",
]
