from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

from flask import current_app


@dataclass(frozen=True)
class CodexStatus:
    installed_version: Optional[str]
    latest_version: Optional[str]
    update_available: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodexUpdateResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CodexUpdateError(RuntimeError):
    """Raised when the Codex CLI cannot be inspected or upgraded."""


def _run_command(command: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    npm_prefix = current_app.config.get("NPM_PREFIX_PATH")
    if npm_prefix:
        env["PATH"] = os.pathsep.join([npm_prefix, env.get("PATH", "")])

    return subprocess.run(  # noqa: S603 subprocess.run without shell
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _fetch_installed_version(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    try:
        completed = _run_command(
            ["npm", "list", "-g", "@openai/codex", "--json", "--depth=0"],
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "npm is not installed on this system."
    except subprocess.TimeoutExpired:
        return None, "Timed out while checking the installed Codex version."
    except OSError as exc:
        return None, f"Failed to check installed Codex version: {exc}"

    if completed.returncode not in (0, 1):
        error_output = completed.stderr.strip() or completed.stdout.strip()
        return None, (
            "Unable to determine installed Codex version."
            + (f" Details: {error_output}" if error_output else "")
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None, "Received malformed response from npm while checking Codex version."

    dependencies = payload.get("dependencies") or {}
    package_info = dependencies.get("@openai/codex")
    if not package_info:
        return None, "Codex CLI is not installed."

    version = package_info.get("version")
    if not version:
        return None, "Unable to parse installed Codex version."

    return version, None


def _fetch_latest_version(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    try:
        completed = _run_command(
            ["npm", "view", "@openai/codex", "version"],
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "npm is not installed on this system."
    except subprocess.TimeoutExpired:
        return None, "Timed out while checking the latest Codex release."
    except OSError as exc:
        return None, f"Failed to query the latest Codex release: {exc}"

    if completed.returncode != 0:
        error_output = completed.stderr.strip() or completed.stdout.strip()
        return None, (
            "Unable to determine the latest Codex release."
            + (f" Details: {error_output}" if error_output else "")
        )

    latest = (completed.stdout or "").strip()
    if not latest:
        return None, "npm did not return a version for the latest Codex release."

    return latest, None


def get_codex_status(*, timeout: int = 20) -> CodexStatus:
    installed_version, installed_error = _fetch_installed_version(timeout=timeout)
    latest_version, latest_error = _fetch_latest_version(timeout=timeout)

    errors = tuple(
        message
        for message in [installed_error, latest_error]
        if message is not None
    )
    update_available = False
    if installed_version and latest_version:
        update_available = installed_version != latest_version

    return CodexStatus(
        installed_version=installed_version,
        latest_version=latest_version,
        update_available=update_available,
        errors=errors,
    )


def install_latest_codex(*, timeout: int = 600) -> CodexUpdateResult:
    raw_command = current_app.config.get("CODEX_UPDATE_COMMAND", "sudo npm install -g @openai/codex")
    if isinstance(raw_command, str):
        parts = shlex.split(raw_command)
    elif isinstance(raw_command, (list, tuple)):
        parts = [str(part) for part in raw_command]
    else:
        raise CodexUpdateError("Invalid CODEX_UPDATE_COMMAND configuration.")

    if not parts:
        raise CodexUpdateError("Codex update command is empty.")

    try:
        completed = _run_command(parts, timeout=timeout)
    except FileNotFoundError as exc:
        raise CodexUpdateError(f"Unable to execute Codex update command: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CodexUpdateError(f"Codex update command timed out after {timeout} seconds.") from exc
    except OSError as exc:
        raise CodexUpdateError(f"Failed to execute Codex update command: {exc}") from exc

    return CodexUpdateResult(
        command=" ".join(shlex.quote(component) for component in parts),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


__all__ = [
    "CodexStatus",
    "CodexUpdateError",
    "CodexUpdateResult",
    "get_codex_status",
    "install_latest_codex",
]
