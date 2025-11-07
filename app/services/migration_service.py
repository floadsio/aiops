from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flask import current_app


@dataclass(frozen=True)
class MigrationResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class MigrationError(RuntimeError):
    """Raised when database migrations cannot be executed."""


def _project_root() -> Path:
    # ``app.root_path`` points to <repo>/app
    return Path(current_app.root_path).parent.resolve()


def _resolve_flask_binary(
    project_root: Path, override: Optional[str | Path]
) -> Path:
    if override is not None:
        candidate = Path(override)
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        return candidate

    venv_candidate = project_root / ".venv" / "bin" / "flask"
    if venv_candidate.exists():
        return venv_candidate

    which_result = shutil.which("flask")
    if which_result:
        return Path(which_result).resolve()

    raise MigrationError(
        "Flask executable not found. Install dependencies with `make sync` or "
        "pass `flask_executable`."
    )


def run_db_upgrade(
    *,
    flask_executable: Optional[str | Path] = None,
    app_module: str = "manage.py",
    timeout: int = 900,
) -> MigrationResult:
    """
    Execute ``flask db upgrade`` and capture the output for UI display.
    """

    project_root = _project_root()
    flask_bin = _resolve_flask_binary(project_root, flask_executable)
    if not flask_bin.exists():
        raise MigrationError(f"Flask executable not found at {flask_bin}")

    command = [str(flask_bin), "--app", app_module, "db", "upgrade"]

    env = os.environ.copy()
    bin_candidates = [
        project_root / ".venv" / "bin",
        Path.home() / ".local" / "bin",
    ]
    path_parts = [str(path) for path in bin_candidates if path.exists()]
    if path_parts:
        env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])

    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise MigrationError(f"Migration command timed out after {timeout} seconds.") from exc
    except FileNotFoundError as exc:
        raise MigrationError("Unable to execute migration command: flask binary missing.") from exc
    except OSError as exc:
        raise MigrationError(f"Failed to execute migration command: {exc}") from exc

    return MigrationResult(
        command=" ".join(shlex.quote(part) for part in command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


__all__ = ["run_db_upgrade", "MigrationResult", "MigrationError"]
