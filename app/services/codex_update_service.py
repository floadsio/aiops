from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

from flask import current_app

VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")


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


def _configured_cli_binary() -> Optional[str]:
    command_map = current_app.config.get("ALLOWED_AI_TOOLS") or {}
    command = command_map.get("codex")
    if not command:
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    return parts[0] if parts else None


def _parse_version(output: str) -> Optional[str]:
    if not output:
        return None
    match = VERSION_PATTERN.search(output)
    if match:
        return match.group(0)
    return None


def _run_command(command: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    npm_prefix = current_app.config.get("NPM_PREFIX_PATH")
    extra_paths = current_app.config.get("CLI_EXTRA_PATHS")
    path_segments = []
    if extra_paths:
        path_segments.append(extra_paths)
    if npm_prefix:
        path_segments.append(npm_prefix)
    path_segments.append(env.get("PATH", ""))
    env["PATH"] = os.pathsep.join(segment for segment in path_segments if segment)

    return subprocess.run(  # noqa: S603 subprocess.run without shell
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _fetch_installed_version_via_cli(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    binary = _configured_cli_binary()
    if not binary:
        return None, None

    attempts = (
        [binary, "--version"],
        [binary, "version"],
    )
    last_error: Optional[str] = None
    for command in attempts:
        try:
            completed = _run_command(command, timeout=timeout)
        except FileNotFoundError:
            return None, f"{binary} is not installed or not on PATH."
        except subprocess.TimeoutExpired:
            last_error = f"Timed out while running {' '.join(command)}."
            continue
        except OSError as exc:
            last_error = f"Failed to run {' '.join(command)}: {exc}"
            continue

        if completed.returncode != 0:
            last_error = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"{binary} exited with {completed.returncode}"
            )
            continue

        version = _parse_version((completed.stdout or "") + (completed.stderr or ""))
        if version:
            return version, None
        last_error = "Unable to parse Codex CLI version from command output."

    return None, last_error


def _fetch_installed_version_via_npm(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
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


def _fetch_installed_version(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    cli_version, cli_error = _fetch_installed_version_via_cli(timeout=timeout)
    if cli_version:
        return cli_version, None

    npm_version, npm_error = _fetch_installed_version_via_npm(timeout=timeout)
    if npm_version:
        return npm_version, None

    if npm_error:
        return None, npm_error
    return None, cli_error or "Unable to determine installed Codex version."


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
