from __future__ import annotations

from pathlib import Path
from typing import Optional

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo


def detect_repo_branch(start_path: Optional[Path | str] = None) -> Optional[str]:
    """Best-effort detection of the current application's git branch."""
    if start_path is None:
        search_root = Path(__file__).resolve().parent
    else:
        candidate = Path(start_path)
        search_root = candidate if candidate.is_dir() else candidate.parent

    try:
        repo = Repo(search_root, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError, GitCommandError, OSError):
        return None

    head = getattr(repo, "head", None)
    if head is None:
        return None
    if getattr(head, "is_detached", False):
        commit = getattr(head, "commit", None)
        hexsha = getattr(commit, "hexsha", "")
        return hexsha[:7] if hexsha else None

    active_branch = getattr(repo, "active_branch", None)
    return getattr(active_branch, "name", None)
