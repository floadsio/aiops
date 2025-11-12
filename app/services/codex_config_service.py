from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

from flask import current_app


class CodexConfigError(RuntimeError):
    """Raised when Codex CLI credentials cannot be managed."""


def _safe_chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        current_app.logger.debug("Unable to set permissions on %s", path)


def _cli_auth_path() -> Path:
    configured = current_app.config.get("CODEX_CONFIG_DIR")
    base_path = Path(configured).expanduser()
    base_path.mkdir(parents=True, exist_ok=True)
    _safe_chmod(base_path, 0o700)
    return base_path / "auth.json"


def _storage_dir(user_id: int) -> Path:
    base = Path(current_app.instance_path) / "codex" / f"user-{user_id}"
    base.mkdir(parents=True, exist_ok=True)
    _safe_chmod(base, 0o700)
    return base


def _storage_auth_path(user_id: int) -> Path:
    return _storage_dir(user_id) / "auth.json"


def _stored_payload(user_id: int) -> str:
    storage_path = _storage_auth_path(user_id)
    if storage_path.exists():
        try:
            return storage_path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem error path
            raise CodexConfigError(
                f"Failed to read Codex auth for user {user_id}: {exc}"
            ) from exc

    legacy_path = _cli_auth_path()
    if legacy_path.exists():
        try:
            payload = legacy_path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            raise CodexConfigError(f"Failed to read legacy Codex auth: {exc}") from exc
        storage_path.write_text(payload, encoding="utf-8")
        _safe_chmod(storage_path, 0o600)
        return payload

    return ""


def save_codex_auth(raw_json: str, *, user_id: Optional[int] = None) -> None:
    if user_id is None:
        raise CodexConfigError("Select a user before saving Codex credentials.")
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise CodexConfigError(f"Codex auth JSON is invalid: {exc}") from exc
    formatted = json.dumps(parsed, indent=2)
    storage_path = _storage_auth_path(user_id)
    try:
        storage_path.write_text(formatted + "\n", encoding="utf-8")
        _safe_chmod(storage_path, 0o600)
    except OSError as exc:  # pragma: no cover - filesystem error path
        raise CodexConfigError(
            f"Failed to write Codex auth for user {user_id}: {exc}"
        ) from exc
    ensure_codex_auth(user_id)


def load_codex_auth(*, user_id: Optional[int] = None) -> str:
    if user_id is None:
        return ""
    return _stored_payload(user_id)


def ensure_codex_auth(user_id: int) -> Path:
    payload = _stored_payload(user_id)
    if not payload:
        raise CodexConfigError("No Codex auth has been saved for this user yet.")
    cli_path = _cli_auth_path()
    try:
        cli_path.write_text(payload, encoding="utf-8")
        _safe_chmod(cli_path, 0o600)
    except OSError as exc:  # pragma: no cover
        raise CodexConfigError(f"Failed to prepare Codex auth file: {exc}") from exc
    return cli_path


def get_user_auth_paths(user_id: int) -> Tuple[Path, Path]:
    return _cli_auth_path(), _storage_auth_path(user_id)


__all__ = [
    "save_codex_auth",
    "load_codex_auth",
    "ensure_codex_auth",
    "get_user_auth_paths",
    "CodexConfigError",
]
