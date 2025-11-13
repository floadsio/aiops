from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from flask import current_app


class CLICommandError(RuntimeError):
    """Raised when an AI CLI update command cannot be executed."""


@dataclass(frozen=True)
class CLICommandResult:
    command: str
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class AIToolVersionInfo:
    installed: str | None = None
    latest: str | None = None
    installed_error: str | None = None
    latest_error: str | None = None


def _project_root() -> Path:
    return Path(current_app.root_path).parent.resolve()


def _collect_extra_paths() -> list[str]:
    paths: list[str] = []
    raw_extra = (current_app.config.get("CLI_EXTRA_PATHS") or "").strip()
    if raw_extra:
        for chunk in raw_extra.split(":"):
            candidate = chunk.strip()
            if candidate:
                paths.append(candidate)
    for candidate in (
        _project_root() / ".venv" / "bin",
        Path.home() / ".local" / "bin",
    ):
        if candidate.exists():
            paths.append(str(candidate))
    return paths


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    extras = _collect_extra_paths()
    if extras:
        env["PATH"] = os.pathsep.join(extras + [env.get("PATH", "")])
    return env


def run_cli_command(raw_command: str, *, timeout: int = 900) -> CLICommandResult:
    try:
        parts = shlex.split(raw_command)
    except ValueError as exc:  # pragma: no cover - invalid configuration
        raise CLICommandError(f"Invalid command configuration: {exc}") from exc

    if not parts:
        raise CLICommandError("Command is empty.")

    try:
        completed = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_project_root(),
            env=_build_env(),
        )
    except FileNotFoundError as exc:
        raise CLICommandError(
            f"Command '{parts[0]}' not found. Check your CLI installation."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CLICommandError(f"CLI command timed out after {timeout} seconds.") from exc
    except OSError as exc:
        raise CLICommandError(f"Failed to execute CLI command: {exc}") from exc

    return CLICommandResult(
        command=" ".join(shlex.quote(part) for part in parts),
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def _summarize_output(result: CLICommandResult) -> str:
    parts = []
    for chunk in (result.stdout, result.stderr):
        if chunk:
            stripped = chunk.strip()
            if stripped:
                parts.append(stripped)
    combined = "\n".join(parts)
    if not combined:
        return ""
    return combined.splitlines()[0]


def _run_version_command(
    command: str | None,
    *,
    timeout: int,
) -> tuple[str | None, str | None]:
    command_text = (command or "").strip()
    if not command_text:
        return None, "Version command not configured."
    try:
        result = run_cli_command(command_text, timeout=timeout)
    except CLICommandError as exc:
        return None, str(exc)

    output = _summarize_output(result)
    if result.ok:
        return output or f"Command exited with {result.returncode}.", None
    return None, output or f"Command exited with {result.returncode}."


def _brew_upgrade_command(package_name: str | None) -> str:
    package = (package_name or "").strip()
    if not package:
        return ""
    return f"brew upgrade {package}"


def _resolve_update_command(tool: str, source: str) -> str:
    config = current_app.config
    normalized_tool = tool.lower()
    normalized_source = source.lower()

    match (normalized_tool, normalized_source):
        case ("codex", "npm"):
            return (config.get("CODEX_UPDATE_COMMAND") or "").strip()
        case ("codex", "brew"):
            return _brew_upgrade_command(config.get("CODEX_BREW_PACKAGE"))
        case ("gemini", "npm"):
            return (config.get("GEMINI_UPDATE_COMMAND") or "").strip()
        case ("gemini", "brew"):
            return _brew_upgrade_command(config.get("GEMINI_BREW_PACKAGE"))
        case ("claude", "npm"):
            return (config.get("CLAUDE_UPDATE_COMMAND") or "").strip()
        case ("claude", "brew"):
            return _brew_upgrade_command(config.get("CLAUDE_BREW_PACKAGE"))
        case _:
            raise CLICommandError(f"Unsupported update source '{source}' for {tool}.")


def get_ai_tool_versions(tool: str, *, timeout: int = 15) -> AIToolVersionInfo:
    config = current_app.config
    normalized = tool.lower().strip()

    match normalized:
        case "codex":
            installed_command = config.get("CODEX_VERSION_COMMAND")
            latest_command = config.get("CODEX_LATEST_VERSION_COMMAND")
        case "gemini":
            installed_command = config.get("GEMINI_VERSION_COMMAND")
            latest_command = config.get("GEMINI_LATEST_VERSION_COMMAND")
        case "claude":
            installed_command = config.get("CLAUDE_VERSION_COMMAND")
            latest_command = config.get("CLAUDE_LATEST_VERSION_COMMAND")
        case _:
            return AIToolVersionInfo()

    installed, installed_error = _run_version_command(
        installed_command,
        timeout=timeout,
    )
    latest, latest_error = _run_version_command(
        latest_command,
        timeout=timeout,
    )
    return AIToolVersionInfo(
        installed=installed,
        latest=latest,
        installed_error=installed_error,
        latest_error=latest_error,
    )


def run_ai_tool_update(tool: str, source: str, *, timeout: int = 900) -> CLICommandResult:
    command = _resolve_update_command(tool, source)
    if not command:
        raise CLICommandError(
            f"No command configured to update {tool.title()} via {source}."
        )
    return run_cli_command(command, timeout=timeout)


__all__ = [
    "CLICommandError",
    "CLICommandResult",
    "AIToolVersionInfo",
    "run_ai_tool_update",
    "run_cli_command",
    "get_ai_tool_versions",
]
