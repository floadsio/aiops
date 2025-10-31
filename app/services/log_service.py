from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


class LogReadError(RuntimeError):
    """Raised when application logs cannot be read."""


@dataclass(frozen=True)
class LogTail:
    content: str
    truncated: bool


def read_log_tail(path: Path, *, max_lines: int = 400) -> LogTail:
    """Read the last ``max_lines`` from ``path``.

    Returns a ``LogTail`` with the aggregated content and a flag indicating whether
    additional content was skipped.
    """

    if max_lines <= 0:
        raise ValueError("max_lines must be positive")

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            buffer = deque(maxlen=max_lines)
            total = 0
            for line in handle:
                buffer.append(line.rstrip("\n"))
                total += 1
    except FileNotFoundError:
        return LogTail(content="", truncated=False)
    except OSError as exc:  # pragma: no cover - filesystem errors
        raise LogReadError(f"Unable to read log file {path}: {exc}") from exc

    truncated = total > max_lines
    content = "\n".join(buffer)
    return LogTail(content=content, truncated=truncated)


__all__ = ["read_log_tail", "LogTail", "LogReadError"]
