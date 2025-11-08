from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flask import current_app

@dataclass(frozen=True)
class UpdateResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class UpdateError(RuntimeError):
    """Raised when the update script cannot be executed."""


def _default_project_root() -> Path:
    # app.root_path points at <project>/app; we need the repo root
    return Path(current_app.root_path).parent.resolve()


def run_update_script(
    script_path: Optional[str | Path] = None,
    *,
    timeout: int = 900,
    extra_env: Optional[dict[str, str]] = None,
) -> UpdateResult:
    """
    Execute the repository update script and capture output for display.

    If ``script_path`` is omitted, ``scripts/update.sh`` relative to the project
    root is used. The script is executed via ``/bin/bash`` so it does not need
    the executable bit set.
    """

    project_root = _default_project_root()
    resolved_script: Path
    if script_path is None:
        resolved_script = project_root / "scripts" / "update.sh"
    else:
        resolved_script = Path(script_path)
        if not resolved_script.is_absolute():
            resolved_script = (project_root / resolved_script).resolve()

    if not resolved_script.exists():
        raise UpdateError(f"Update script not found at {resolved_script}")

    if resolved_script.is_dir():
        raise UpdateError(f"Update script path {resolved_script} is a directory, not a file.")

    command = ["/bin/bash", str(resolved_script)]
    env = os.environ.copy()
    # Ensure the virtualenv and local tools (uv-installed codex, etc.) are on PATH
    bin_candidates = [
        project_root / ".venv" / "bin",
        Path.home() / ".local" / "bin",
    ]
    path_parts = [str(path) for path in bin_candidates if path.exists()]
    if path_parts:
        env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])
    if extra_env:
        env.update({key: str(value) for key, value in extra_env.items() if value is not None})

    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:  # /bin/bash missing (unlikely)
        raise UpdateError("Unable to execute update script: /bin/bash not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"Update script timed out after {timeout} seconds.") from exc
    except OSError as exc:
        raise UpdateError(f"Failed to execute update script: {exc}") from exc

    return UpdateResult(
        command=" ".join(shlex.quote(part) for part in command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


__all__ = ["run_update_script", "UpdateResult", "UpdateError"]
