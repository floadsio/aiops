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
    "run_ai_tool_update",
    "run_cli_command",
]
