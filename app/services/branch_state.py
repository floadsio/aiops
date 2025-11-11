from __future__ import annotations

from pathlib import Path

from flask import current_app
from git import Repo, GitCommandError

from ..git_info import list_repo_branches

BRANCH_MARKER_FILENAME = "current_branch.txt"


def _marker_path() -> Path:
    path = Path(current_app.instance_path) / BRANCH_MARKER_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_recorded_branch() -> str | None:
    marker = _marker_path()
    if not marker.exists():
        return None
    try:
        value = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def remember_branch(branch: str | None) -> None:
    marker = _marker_path()
    if branch:
        try:
            marker.write_text(branch.strip(), encoding="utf-8")
        except OSError:
            current_app.logger.warning("Unable to write branch marker %s", marker)
    else:
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            current_app.logger.debug("Branch marker removal failed; ignoring.", exc_info=True)


def current_repo_branch() -> str:
    repo_root = Path(current_app.root_path).parent
    try:
        repo = Repo(repo_root)
        if repo.head.is_detached:
            return repo.head.commit.hexsha[:7]
        return repo.active_branch.name
    except Exception:  # noqa: BLE001 - best effort
        return "main"


def available_branches() -> list[str]:
    repo_root = Path(current_app.root_path).parent
    detected = list_repo_branches(repo_root, include_remote=True)
    branches: list[str] = []
    current = current_repo_branch()
    if current:
        branches.append(current)
    for name in detected:
        if name not in branches:
            branches.append(name)
    if not branches:
        branches.append("main")
    return branches


def configure_branch_form(form, *, current_branch: str | None = None) -> None:
    branches = available_branches()
    recorded = load_recorded_branch()
    choices = [(branch, branch) for branch in branches]
    if current_branch and current_branch not in [value for value, _ in choices]:
        choices.insert(0, (current_branch, current_branch))
    if recorded and recorded not in [value for value, _ in choices]:
        choices.insert(0, (recorded, recorded))
    form.branch.choices = choices
    if form.is_submitted():
        return
    default_branch = recorded or current_branch
    if default_branch:
        form.branch.data = default_branch
    elif not form.branch.data and choices:
        form.branch.data = choices[0][0]


class BranchSwitchError(RuntimeError):
    """Raised when git branch switch fails."""


def switch_repo_branch(target_branch: str) -> None:
    repo_root = Path(current_app.root_path).parent
    try:
        repo = Repo(repo_root)
    except Exception as exc:  # noqa: BLE001
        raise BranchSwitchError(f"Unable to open repository at {repo_root}: {exc}") from exc

    cleaned = (target_branch or "").strip()
    if not cleaned:
        raise BranchSwitchError("Branch name is required.")

    try:
        repo.git.checkout(cleaned)
    except GitCommandError as exc:
        raise BranchSwitchError(f"git checkout {cleaned} failed: {exc}") from exc
