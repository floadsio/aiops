from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

from flask import current_app

from .linux_users import resolve_linux_username
from .sudo_service import SudoError, run_as_user

if TYPE_CHECKING:
    from ..models import User


class AIStatusError(RuntimeError):
    """Raised when an AI tool status cannot be determined."""


@dataclass
class ToolStatus:
    tool: str
    command: str
    stdout: str
    stderr: str
    returncode: int

    @property
    def success(self) -> bool:
        return self.returncode == 0


def _prepare_command(raw_command: str, extra_args: list[str]) -> list[str]:
    try:
        parts = shlex.split(raw_command)
    except ValueError as exc:  # pragma: no cover - defensive
        raise AIStatusError(f"Invalid command configuration: {exc}") from exc
    if not parts:
        raise AIStatusError("AI status command is empty.")
    return parts + extra_args


def get_claude_status(user: User, *, timeout: int = 15) -> ToolStatus:
    """Run `claude -p status` as the user's Linux account."""
    linux_username = resolve_linux_username(user)
    if not linux_username:
        raise AIStatusError(
            "No Linux user mapping is configured for your account. "
            "Ask an administrator to set your Linux user in Settings → Users."
        )

    command_str = current_app.config.get("CLAUDE_COMMAND", "claude")
    command = _prepare_command(command_str, ["-p", "status"])

    try:
        result = run_as_user(
            linux_username,
            command,
            timeout=timeout,
            check=False,
        )
    except SudoError as exc:
        raise AIStatusError(f"Unable to run Claude status: {exc}") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    return ToolStatus(
        tool="Claude",
        command=" ".join(shlex.quote(part) for part in command),
        stdout=stdout,
        stderr=stderr,
        returncode=result.returncode,
    )


__all__ = [
    "AIStatusError",
    "ToolStatus",
    "get_claude_status",
]
