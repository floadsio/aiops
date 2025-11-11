from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

from flask import current_app

PACKAGE_NAME = "@anthropic/claude-cli"
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")


@dataclass(frozen=True)
class ClaudeStatus:
    installed_version: Optional[str]
    latest_version: Optional[str]
    update_available: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaudeUpdateResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ClaudeUpdateError(RuntimeError):
    """Raised when the Claude CLI cannot be inspected or upgraded."""


def _configured_cli_binary() -> Optional[str]:
    command_map = current_app.config.get("ALLOWED_AI_TOOLS") or {}
    command = command_map.get("claude")
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


def _brew_formula_name() -> Optional[str]:
    configured = current_app.config.get("CLAUDE_BREW_PACKAGE")
    if configured:
        return configured
    binary = _configured_cli_binary()
    if binary:
        basename = os.path.basename(binary)
        if basename == "claude":
            return "claude-code"
        return basename
    return "claude-code"


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

    return subprocess.run(
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
        last_error = "Unable to parse Claude CLI version from command output."

    return None, last_error


def _fetch_installed_version_via_npm(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    try:
        completed = _run_command(
            ["npm", "list", "-g", PACKAGE_NAME, "--json", "--depth=0"],
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "npm is not installed on this system."
    except subprocess.TimeoutExpired:
        return None, "Timed out while checking the installed Claude CLI version."
    except OSError as exc:
        return None, f"Failed to check installed Claude CLI version: {exc}"

    if completed.returncode not in (0, 1):
        error_output = completed.stderr.strip() or completed.stdout.strip()
        return None, (
            "Unable to determine installed Claude CLI version."
            + (f" Details: {error_output}" if error_output else "")
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None, "Received malformed response from npm while checking Claude CLI version."

    dependencies = payload.get("dependencies") or {}
    package_info = dependencies.get(PACKAGE_NAME)
    if not package_info:
        return None, "Claude CLI is not installed."

    version = package_info.get("version")
    if not version:
        return None, "Unable to parse installed Claude CLI version."

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
    return None, cli_error or "Unable to determine installed Claude CLI version."


def _fetch_latest_version_via_npm(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    try:
        completed = _run_command(
            ["npm", "view", PACKAGE_NAME, "version"],
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "npm is not installed on this system."
    except subprocess.TimeoutExpired:
        return None, "Timed out while checking the latest Claude CLI release."
    except OSError as exc:
        return None, f"Failed to query the latest Claude CLI release: {exc}"

    if completed.returncode != 0:
        error_output = completed.stderr.strip() or completed.stdout.strip()
        return None, (
            "Unable to determine the latest Claude CLI release."
            + (f" Details: {error_output}" if error_output else "")
        )

    latest = (completed.stdout or "").strip()
    if not latest:
        return None, "npm did not return a version for the latest Claude CLI release."

    return latest, None


def _fetch_latest_version_via_brew(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    formula = _brew_formula_name()
    if not formula:
        return None, None
    try:
        completed = _run_command(
            ["brew", "info", "--json=v2", formula],
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "brew is not installed on this system."
    except subprocess.TimeoutExpired:
        return None, "Timed out while checking the latest Claude CLI release via Homebrew."
    except OSError as exc:
        return None, f"Failed to query Homebrew for Claude CLI release: {exc}"

    if completed.returncode != 0:
        error_output = completed.stderr.strip() or completed.stdout.strip()
        return None, (
            f"Homebrew could not provide info for {formula}."
            + (f" Details: {error_output}" if error_output else "")
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None, "Received malformed response from brew while checking Claude CLI version."

    entries = payload.get("formulae") or payload.get("casks") or []
    entry = entries[0] if entries else None
    version = None
    if entry:
        versions = entry.get("versions") or {}
        version = versions.get("stable") or versions.get("version")
        if not version:
            version = entry.get("version") or entry.get("bundle_short_version") or entry.get("bundle_version")
        if version and isinstance(version, str) and "," in version:
            version = version.split(",", 1)[0]
    if not version:
        return None, "Unable to parse Claude CLI version from Homebrew response."
    return version, None


def _fetch_latest_version(*, timeout: int) -> tuple[Optional[str], Optional[str]]:
    npm_version, npm_error = _fetch_latest_version_via_npm(timeout=timeout)
    if npm_version:
        return npm_version, None

    brew_version, brew_error = _fetch_latest_version_via_brew(timeout=timeout)
    if brew_version:
        return brew_version, None

    if brew_error:
        return None, brew_error
    return None, npm_error


def get_claude_status(*, timeout: int = 20) -> ClaudeStatus:
    installed_version, installed_error = _fetch_installed_version(timeout=timeout)
    latest_version, latest_error = _fetch_latest_version(timeout=timeout)

    errors = tuple(message for message in (installed_error, latest_error) if message)
    update_available = False
    if installed_version and latest_version:
        update_available = installed_version != latest_version

    return ClaudeStatus(
        installed_version=installed_version,
        latest_version=latest_version,
        update_available=update_available,
        errors=errors,
    )


def install_latest_claude(*, timeout: int = 600) -> ClaudeUpdateResult:
    raw_command = current_app.config.get(
        "CLAUDE_UPDATE_COMMAND", f"sudo npm install -g {PACKAGE_NAME}"
    )
    if isinstance(raw_command, str):
        parts = shlex.split(raw_command)
    elif isinstance(raw_command, (list, tuple)):
        parts = [str(part) for part in raw_command]
    else:
        raise ClaudeUpdateError("Invalid CLAUDE_UPDATE_COMMAND configuration.")

    if not parts:
        raise ClaudeUpdateError("Claude update command is empty.")

    try:
        completed = _run_command(parts, timeout=timeout)
    except FileNotFoundError as exc:
        raise ClaudeUpdateError(f"Unable to execute Claude update command: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaudeUpdateError(
            f"Claude update command timed out after {timeout} seconds."
        ) from exc
    except OSError as exc:
        raise ClaudeUpdateError(f"Failed to execute Claude update command: {exc}") from exc

    return ClaudeUpdateResult(
        command=" ".join(shlex.quote(component) for component in parts),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


__all__ = [
    "ClaudeStatus",
    "ClaudeUpdateError",
    "ClaudeUpdateResult",
    "get_claude_status",
    "install_latest_claude",
]
