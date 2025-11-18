from __future__ import annotations

import json
import pwd
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
    configured = current_app.config.get("CODEX_CONFIG_DIR", str(Path.home() / ".codex"))
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


def sync_codex_credentials_to_cli_home(user_id: int) -> Path:
    """Copy the user's codex auth file into the CLI home (typically ~/.codex).

    This ensures that when running commands as a different Linux user, they can
    access the codex credentials from their own home directory.

    Args:
        user_id: The user ID whose credentials should be synced

    Returns:
        Path to the CLI auth file that was created

    Raises:
        CodexConfigError: If credentials cannot be synced
    """
    payload = _stored_payload(user_id)
    if not payload:
        raise CodexConfigError("No Codex auth has been saved for this user yet.")

    cli_path = _cli_auth_path()
    try:
        cli_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_chmod(cli_path.parent, 0o700)
        cli_path.write_text(payload, encoding="utf-8")
        _safe_chmod(cli_path, 0o600)
    except OSError as exc:  # pragma: no cover
        raise CodexConfigError(f"Failed to sync Codex auth file: {exc}") from exc

    return cli_path


def sync_codex_credentials_for_linux_user(
    user_id: int, linux_username: str
) -> Path:
    """Copy codex credentials to a specific Linux user's home directory.

    This is used for per-user sessions where the command runs as a different
    Linux user. The credentials are copied via sudo to ensure proper ownership.

    Args:
        user_id: The database user ID whose credentials should be synced
        linux_username: The Linux username to copy credentials for

    Returns:
        Path to the auth file in the Linux user's home directory

    Raises:
        CodexConfigError: If credentials cannot be synced
    """
    from .sudo_service import SudoError, run_as_user

    # Get the payload from storage
    payload = _stored_payload(user_id)
    if not payload:
        raise CodexConfigError("No Codex auth has been saved for this user yet.")

    # Get target user's home directory
    try:
        user_info = pwd.getpwnam(linux_username)
    except KeyError as exc:
        raise CodexConfigError(f"Unknown Linux user: {linux_username}") from exc

    target_dir = Path(user_info.pw_dir) / ".codex"
    target_auth = target_dir / "auth.json"

    # Create the directory and write the file as the target user
    try:
        # Create .codex directory
        run_as_user(linux_username, ["mkdir", "-p", str(target_dir)], timeout=10)

        # Write auth file via temporary file to avoid permission issues
        # We write to a temp location as syseng, then move it as the target user
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tmp:
            tmp.write(payload)
            tmp_path = tmp.name

        try:
            # Move temp file to target location and set permissions
            run_as_user(linux_username, ["cp", tmp_path, str(target_auth)], timeout=10)
            run_as_user(linux_username, ["chmod", "600", str(target_auth)], timeout=10)
            run_as_user(linux_username, ["chmod", "700", str(target_dir)], timeout=10)
        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink()
            except OSError:
                current_app.logger.debug("Failed to remove temp file %s", tmp_path)

    except SudoError as exc:
        raise CodexConfigError(
            f"Failed to sync codex credentials for {linux_username}: {exc}"
        ) from exc

    return target_auth


__all__ = [
    "save_codex_auth",
    "load_codex_auth",
    "ensure_codex_auth",
    "sync_codex_credentials_to_cli_home",
    "sync_codex_credentials_for_linux_user",
    "get_user_auth_paths",
    "CodexConfigError",
]
