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


def list_repo_branches(
    start_path: Optional[Path | str] = None,
    *,
    include_remote: bool = True,
) -> list[str]:
    """Return available git branches for the repository containing start_path."""
    if start_path is None:
        search_root = Path(__file__).resolve().parent
    else:
        candidate = Path(start_path)
        search_root = candidate if candidate.is_dir() else candidate.parent

    try:
        repo = Repo(search_root, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError, GitCommandError, OSError):
        return []

    names: list[str] = []
    try:
        heads = getattr(repo, "heads", None) or getattr(repo, "branches", None)
        if heads:
            names.extend(head.name for head in heads if getattr(head, "name", None))
    except Exception:  # noqa: BLE001
        pass

    if include_remote:
        try:
            for remote in getattr(repo, "remotes", []):
                for ref in getattr(remote, "refs", []):
                    remote_head = getattr(ref, "remote_head", None)
                    if remote_head:
                        names.append(remote_head)
        except Exception:  # noqa: BLE001
            pass

    detected = detect_repo_branch(search_root)
    if detected:
        names.insert(0, detected)

    ordered: list[str] = []
    for name in names:
        if name and name not in ordered:
            ordered.append(name)
    return ordered
