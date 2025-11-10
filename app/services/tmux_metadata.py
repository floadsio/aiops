from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from flask import current_app


def _metadata_path() -> Path:
    path = Path(current_app.instance_path) / "tmux_tools.json"
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
    return path


def _load_metadata() -> dict[str, str]:
    path = _metadata_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_metadata(data: dict[str, str]) -> None:
    path = _metadata_path()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def record_tmux_tool(target: str, tool: str) -> None:
    if not target:
        return
    data = _load_metadata()
    data[target] = tool
    _save_metadata(data)


def get_tmux_tool(target: str) -> Optional[str]:
    if not target:
        return None
    data = _load_metadata()
    return data.get(target)


def prune_tmux_tools(valid_targets: Iterable[str]) -> None:
    targets = set(valid_targets)
    data = _load_metadata()
    stale = [key for key in data if key not in targets]
    if not stale:
        return
    for key in stale:
        data.pop(key, None)
    _save_metadata(data)


__all__ = ["record_tmux_tool", "get_tmux_tool", "prune_tmux_tools"]
