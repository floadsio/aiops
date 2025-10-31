from __future__ import annotations

import logging
import os
import shlex
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Optional

from datetime import datetime, timezone

from flask import current_app
from git import GitCommandError, Repo, exc
from git.remote import Remote

from ..extensions import db
from ..models import Project
from ..services.key_service import resolve_private_key_path

log = logging.getLogger(__name__)


def _project_slug(project: Project) -> str:
    name = getattr(project, "name", "") or f"project-{project.id}"
    slug = name.lower().translate(str.maketrans({c: "-" for c in " ./\\:"}))
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or f"project-{project.id}"


def _project_repo_root() -> Path:
    root = Path(current_app.config["REPO_STORAGE_PATH"]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _default_project_path(project: Project) -> Path:
    root = _project_repo_root()
    base_slug = _project_slug(project)
    candidate = root / base_slug
    suffix = 1
    existing = Path(getattr(project, "local_path", ""))
    while candidate.exists() and candidate != existing:
        if (candidate / ".git").exists():
            suffix += 1
            candidate = root / f"{base_slug}-{suffix}"
        else:
            break
    return candidate


def _relocate_project_path(project: Project) -> Path:
    new_path = _default_project_path(project)
    new_path.mkdir(parents=True, exist_ok=True)
    old_path = project.local_path
    project.local_path = str(new_path)
    try:
        db.session.add(project)
        db.session.commit()
    except Exception:  # pragma: no cover - protect against failed commit
        db.session.rollback()
        raise
    current_app.logger.warning(
        "Project %s local checkout path reset from %s to %s due to inaccessible path.",
        getattr(project, "name", project.id),
        old_path,
        new_path,
    )
    return new_path


def _normalize_private_key_path(path: Optional[str]) -> Optional[Path]:
    resolved = resolve_private_key_path(path)
    if resolved is None:
        return None
    return _sanitize_private_key(resolved)


def _sanitize_private_key(path: Path) -> Path:
    """Normalize private key line endings to avoid OpenSSH parsing issues."""
    try:
        data = path.read_bytes()
    except OSError:
        return path

    if b"\r\n" not in data:
        return path

    sanitized = data.replace(b"\r\n", b"\n")
    if sanitized == data:
        return path

    try:
        path.write_bytes(sanitized)
        os.chmod(path, 0o600)
        log.info("Normalized line endings for SSH key %s", path)
    except OSError:
        log.warning("Unable to normalize SSH key %s", path)
    return path


def _is_valid_private_key(path: Optional[str]) -> bool:
    key_path = _normalize_private_key_path(path)
    if not key_path:
        return False
    if not key_path.exists() or not key_path.is_file():
        return False
    try:
        header = key_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return False
    return header.startswith("-----BEGIN")


def _resolve_project_ssh_key_path(project: Project, *, invalid: Optional[set[str]] = None) -> Optional[str]:
    invalid = invalid or set()

    project_key = getattr(project, "ssh_key", None)
    if project_key:
        if (
            (normalized_key := _normalize_private_key_path(project_key.private_key_path))
            and _is_valid_private_key(str(normalized_key))
            and str(normalized_key) not in invalid
        ):
            return str(normalized_key)
        elif project_key.private_key_path:
            log.warning(
                "Project %s references SSH key %s without usable private material; skipping.",
                project.id,
                project_key.name,
            )

    tenant = getattr(project, "tenant", None)
    if tenant:
        sorted_keys = sorted(
            tenant.ssh_keys,
            key=lambda key: key.created_at or datetime.min,
        )
        for key in sorted_keys:
            if (
                (normalized_key := _normalize_private_key_path(key.private_key_path))
                and _is_valid_private_key(str(normalized_key))
                and str(normalized_key) not in invalid
            ):
                return str(normalized_key)
            elif key.private_key_path:
                log.debug(
                    "Tenant %s SSH key %s lacks usable private material; skipping.",
                    tenant.id,
                    key.name,
                )
    return None


def _ensure_known_hosts_file() -> Optional[str]:
    instance_path = getattr(current_app, "instance_path", None)
    if not instance_path:
        return None
    path = Path(instance_path) / "known_hosts"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
            os.chmod(path, 0o600)
    except OSError as exc:  # pragma: no cover - filesystem errors
        log.warning("Unable to prepare known_hosts file at %s: %s", path, exc)
        return None
    return str(path)


def _build_git_env(ssh_key_path: Optional[str]) -> dict[str, str]:
    known_hosts_path = _ensure_known_hosts_file()
    parts = ["ssh"]
    if ssh_key_path:
        parts.extend(["-i", shlex.quote(ssh_key_path), "-o", "IdentitiesOnly=yes"])
    parts.extend(
        [
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]
    )
    if known_hosts_path:
        parts.extend(
            [
                "-o",
                f"UserKnownHostsFile={shlex.quote(known_hosts_path)}",
            ]
        )
    command = " ".join(parts)
    return {"GIT_SSH_COMMAND": command}


def ensure_repo_checkout(project: Project) -> Repo:
    storage_root = _project_repo_root()
    path = Path(project.local_path).expanduser()
    try:
        resolved_path = path.resolve(strict=False)
    except TypeError:  # pragma: no cover - older Python compatibility
        resolved_path = path.resolve()
    resolved_root = storage_root.resolve()
    within_storage = resolved_path == resolved_root or resolved_root in resolved_path.parents
    if not within_storage:
        path = _relocate_project_path(project)
        resolved_path = path.resolve()

    if path.exists() and (path / ".git").exists():
        try:
            return Repo(path)
        except Exception:  # noqa: BLE001
            path = _relocate_project_path(project)
    else:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            path = _relocate_project_path(project)

    invalid_keys: set[str] = set()

    def _attempt_clone(env: dict[str, str] | None) -> Repo:
        return Repo.clone_from(
            project.repo_url,
            path,
            branch=project.default_branch,
            env=env or None,
        )

    while True:
        key_path = _resolve_project_ssh_key_path(project, invalid=invalid_keys)
        env = _build_git_env(key_path)
        try:
            return _attempt_clone(env if env else None)
        except exc.GitCommandError as err:
            message = str(err).lower()
            if key_path and ("invalid format" in message or "permission denied" in message):
                invalid_keys.add(key_path)
                log.warning(
                    "Git clone failed for %s with key %s; retrying without it.",
                    project.name,
                    key_path,
                )
                if path.exists() and not (path / ".git").exists():
                    # cleanup partial clone directory
                    for item in path.iterdir():
                        if item.is_file():
                            item.unlink(missing_ok=True)
                        elif item.is_dir():
                            import shutil

                            shutil.rmtree(item, ignore_errors=True)
                continue
            log.exception("Failed to clone repository %s", project.repo_url)
            raise RuntimeError(f"Git clone failed: {err}")


def _discard_local_changes(repo: Repo) -> list[str]:
    """Discard local changes to prepare for a clean pull."""
    steps: list[str] = []
    repo.git.reset("--hard", "HEAD")
    steps.append("git reset --hard HEAD")
    repo.git.clean("-fd")
    steps.append("git clean -fd")
    return steps


def _select_remote(repo: Repo) -> Remote:
    if not repo.remotes:
        raise RuntimeError("Repository has no remotes configured.")
    for remote in repo.remotes:
        if remote.name == "origin":
            return remote
    return repo.remotes[0]


def run_git_action(
    project: Project,
    action: str,
    ref: Optional[str] = None,
    *,
    clean: bool = False,
) -> str:
    repo = ensure_repo_checkout(project)
    messages: list[str] = []
    invalid_keys: set[str] = set()

    def _run_with_env(env: dict[str, str] | None) -> str:
        if action == "pull":
            if clean:
                log.info("Performing clean pull for project %s", project.name)
                steps = _discard_local_changes(repo)
                messages.extend(f"Executed: {step}" for step in steps)
            remote = _select_remote(repo)
            target = ref or project.default_branch
            messages.append(f"Pulling {remote.name}/{target} …")
            env_context = repo.git.custom_environment(**(env or {})) if env else nullcontext()
            with env_context:
                pull_results = remote.pull(target)
            if pull_results:
                pull_messages: list[str] = []
                for result in pull_results:
                    summary = getattr(result, "summary", None) or getattr(result, "note", None)
                    if summary:
                        pull_messages.append(summary.strip())
                messages.extend(pull_messages or ["Pull completed."])
            else:
                messages.append("Already up to date.")
            status = repo.git.status("--short", "--branch").strip()
            if status:
                messages.append("Working tree status:\n" + status)
            return "\n".join(messages)
        if action == "push":
            remote = _select_remote(repo)
            target = ref or project.default_branch
            messages.append(f"Pushing to {remote.name}/{target} …")
            env_context = repo.git.custom_environment(**(env or {})) if env else nullcontext()
            with env_context:
                push_results = remote.push(target)
            if push_results:
                push_messages: list[str] = []
                for result in push_results:
                    summary = getattr(result, "summary", None) or getattr(result, "note", None)
                    if summary:
                        push_messages.append(summary.strip())
                messages.extend(push_messages or ["Push completed."])
            else:
                messages.append("Push completed.")
            return "\n".join(messages)
        if action == "status":
            return repo.git.status("--short", "--branch")
        raise ValueError(f"Unsupported git action: {action}")

    while True:
        key_path = _resolve_project_ssh_key_path(project, invalid=invalid_keys)
        ssh_key_env = _build_git_env(key_path)
        try:
            return _run_with_env(ssh_key_env)
        except GitCommandError as err:
            message = str(err).lower()
            if key_path and ("invalid format" in message or "permission denied" in message):
                invalid_keys.add(key_path)
                log.warning(
                    "Git action %s failed for %s with key %s; retrying without it.",
                    action,
                    project.name,
                    key_path,
                )
                continue
            log.exception("Git action %s failed for %s", action, project.name)
            raise RuntimeError(f"Git action failed: {err}") from err


def get_repo_status(project: Project) -> dict[str, Any]:
    try:
        repo = ensure_repo_checkout(project)
    except Exception as exc:  # noqa: BLE001
        log.warning("Unable to inspect repository for project %s: %s", project.name, exc)
        return {
            "branch": "unknown",
            "dirty": None,
            "untracked_files": [],
            "status_summary": "",
            "last_pull": None,
            "last_pull_display": None,
            "error": str(exc),
        }

    dirty = repo.is_dirty()
    active_branch = getattr(repo.head, "ref", None)
    branch_name = active_branch.name if active_branch else "detached"
    status_summary = repo.git.status("--short", "--branch").strip()

    fetch_head = Path(repo.git_dir) / "FETCH_HEAD"
    last_pull_iso: Optional[str] = None
    last_pull_display: Optional[str] = None
    last_author: Optional[str] = None
    last_commit_ts: Optional[datetime] = None
    if fetch_head.exists():
        fetched_at = datetime.fromtimestamp(fetch_head.stat().st_mtime, tz=timezone.utc)
        last_pull_iso = fetched_at.isoformat()
        last_pull_display = fetched_at.astimezone().strftime("%b %d, %Y • %H:%M %Z")

    commit_hash = None
    commit_subject = None
    try:
        head_commit = repo.head.commit
        commit_hash = head_commit.hexsha[:12]
        commit_subject = head_commit.message.splitlines()[0]
        last_author = head_commit.author.name
        committed_at = head_commit.committed_datetime
        if committed_at.tzinfo is None:
            committed_at = committed_at.replace(tzinfo=timezone.utc)
        last_commit_ts = committed_at
    except Exception:  # noqa: BLE001
        head_commit = None

    return {
        "branch": branch_name,
        "dirty": dirty,
        "untracked_files": repo.untracked_files,
        "status_summary": status_summary,
        "last_pull": last_pull_iso,
        "last_pull_display": last_pull_display,
        "last_commit_author": last_author,
        "last_commit_timestamp": last_commit_ts.isoformat() if last_commit_ts else None,
        "last_commit_display": (
            last_commit_ts.astimezone().strftime("%b %d, %Y • %H:%M %Z")
            if last_commit_ts
            else None
        ),
        "last_commit_hash": commit_hash,
        "last_commit_subject": commit_subject,
    }
