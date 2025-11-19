from __future__ import annotations

import logging
import os
import shlex
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from flask import current_app
from git import GitCommandError, Repo, exc
from git.remote import Remote

from ..extensions import db
from ..models import Project, SSHKey
from ..services.key_service import resolve_private_key_path
from .linux_users import resolve_linux_username
from .sudo_service import SudoError, run_as_user
from . import cli_git_service

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectSSHKeyReference:
    """Capture the SSH key information selected for a project."""

    key: Optional[SSHKey]
    path: str
    source: Optional[str] = None


def _project_slug(project: Project) -> str:
    name = getattr(project, "name", "") or f"project-{project.id}"
    translation_map: dict[str, str | int] = {c: "-" for c in " ./\\:"}
    slug = name.lower().translate(str.maketrans(translation_map))
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
        os.chmod(path, 0o640)
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


def _select_project_ssh_key(
    project: Project, *, invalid: Optional[set[str]] = None
) -> tuple[Optional[str], Optional[SSHKey], Optional[str]]:
    invalid = invalid or set()

    project_key = getattr(project, "ssh_key", None)
    if project_key:
        # Prefer encrypted key in database over filesystem key
        if project_key.encrypted_private_key:
            # Key is in database, return the model itself
            return None, project_key, "project"

        # Fall back to filesystem key
        normalized_key = _normalize_private_key_path(project_key.private_key_path)
        if (
            normalized_key
            and _is_valid_private_key(str(normalized_key))
            and str(normalized_key) not in invalid
        ):
            return str(normalized_key), project_key, "project"
        elif project_key.private_key_path:
            log.warning(
                "Project %s references SSH key %s without usable private material; skipping.",
                project.id,
                project_key.name,
            )

    tenant = getattr(project, "tenant", None)
    if tenant:
        tenant_keys = getattr(tenant, "ssh_keys", []) or []
        sorted_keys = sorted(
            tenant_keys,
            key=lambda key: getattr(key, "created_at", None) or datetime.min,
        )
        for key in sorted_keys:
            # Prefer encrypted key in database over filesystem key
            if key.encrypted_private_key:
                # Key is in database, return the model itself
                return None, key, "tenant"

            # Fall back to filesystem key
            normalized_key = _normalize_private_key_path(key.private_key_path)
            if (
                normalized_key
                and _is_valid_private_key(str(normalized_key))
                and str(normalized_key) not in invalid
            ):
                return str(normalized_key), key, "tenant"
            elif key.private_key_path:
                log.debug(
                    "Tenant %s SSH key %s lacks usable private material; skipping.",
                    tenant.id,
                    key.name,
                )

    return None, None, None


def _resolve_project_ssh_key_path(
    project: Project, *, invalid: Optional[set[str]] = None
) -> Optional[str]:
    key_path, _, _ = _select_project_ssh_key(project, invalid=invalid)
    return key_path


def resolve_project_ssh_key_path(project: Project) -> Optional[str]:
    """Expose the sanitized SSH key path for a project or its tenant."""

    return _resolve_project_ssh_key_path(project)


def resolve_project_ssh_key_reference(
    project: Project,
) -> Optional[ProjectSSHKeyReference]:
    """Return the SSH key reference (model + path) selected for a project."""

    key_path, key_obj, source = _select_project_ssh_key(project)
    if not key_path:
        return None
    return ProjectSSHKeyReference(key=key_obj, path=key_path, source=source)


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


def build_project_git_env(project: Project) -> dict[str, str]:
    """Return a Git environment configured for a project's SSH credentials."""
    key_path = _resolve_project_ssh_key_path(project)
    return _build_git_env(key_path)


def ensure_repo_checkout(project: Project, user: Optional[object] = None) -> Repo:
    # If user is provided, use their workspace; otherwise use managed checkout
    if user is not None:
        from .workspace_service import get_workspace_path, workspace_exists

        workspace_path = get_workspace_path(project, user)
        if workspace_path is None:
            raise RuntimeError(
                f"Cannot determine workspace path for user {getattr(user, 'email', 'unknown')}"
            )

        # If workspace exists with .git, return it
        if workspace_exists(project, user):
            return Repo(workspace_path)

        # Otherwise, workspace needs to be initialized
        raise RuntimeError(
            f"Workspace not initialized at {workspace_path}. "
            "Please initialize the workspace first."
        )

    # Fallback to managed checkout path (legacy behavior)
    storage_root = _project_repo_root()
    path = Path(project.local_path).expanduser()
    try:
        resolved_path = path.resolve(strict=False)
    except TypeError:  # pragma: no cover - older Python compatibility
        resolved_path = path.resolve()
    resolved_root = storage_root.resolve()
    within_storage = (
        resolved_path == resolved_root or resolved_root in resolved_path.parents
    )
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

    # Try CLI tools first if available (GitHub/GitLab with PAT)
    if cli_git_service.supports_cli_git(project):
        try:
            cli_git_service.clone_repo(project, path, branch=project.default_branch)
            return Repo(path)
        except cli_git_service.CliGitServiceError as err:
            log.warning(
                "CLI git clone failed for %s, falling back to SSH: %s",
                project.name,
                err,
            )
            # Fall through to SSH-based clone

    # Fallback to SSH-based clone
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
            if key_path and (
                "invalid format" in message or "permission denied" in message
            ):
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


def _build_user_git_env() -> dict[str, str]:
    return {
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
    }


def _run_git_command_as_user(
    linux_username: str,
    repo_path: Path,
    args: list[str],
    *,
    env: Optional[dict[str, str]] = None,
    timeout: float = 60.0,
) -> str:
    command = ["git", "-C", str(repo_path), *args]
    result = run_as_user(
        linux_username,
        command,
        env=env,
        timeout=timeout,
    )
    output_parts: list[str] = []
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        output_parts.append(stdout)
    if stderr:
        output_parts.append(stderr)
    return "\n".join(output_parts)


def _select_remote(repo: Repo) -> Remote:
    if not repo.remotes:
        raise RuntimeError("Repository has no remotes configured.")
    for remote in repo.remotes:
        if remote.name == "origin":
            return remote
    return repo.remotes[0]


def commit_project_files(
    project: Project,
    files: list[Path | str],
    message: str,
    user: Optional[object] = None,
) -> bool:
    """Stage the provided files, commit them, and return True if a commit was created."""
    repo = ensure_repo_checkout(project, user=user)
    root = Path(repo.working_tree_dir).resolve()
    relative_paths: list[str] = []
    for item in files:
        resolved = Path(item).expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:
            raise RuntimeError(f"Unable to resolve path {item!s}") from None
        try:
            rel_path = resolved.relative_to(root)
        except ValueError:
            raise RuntimeError(f"Path {resolved} is not inside the project repository.")
        relative_paths.append(str(rel_path))

    if not relative_paths:
        return False

    try:
        repo.index.add(relative_paths)
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to stage files for commit: {exc}") from exc

    if not repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        return False

    commit_env = build_project_git_env(project) or {}
    author_name = current_app.config.get("GIT_AUTHOR_NAME", "AI Ops Dashboard")
    author_email = current_app.config.get("GIT_AUTHOR_EMAIL", "aiops@example.com")
    commit_env.setdefault("GIT_AUTHOR_NAME", author_name)
    commit_env.setdefault("GIT_AUTHOR_EMAIL", author_email)
    commit_env.setdefault("GIT_COMMITTER_NAME", author_name)
    commit_env.setdefault("GIT_COMMITTER_EMAIL", author_email)

    env_context = (
        repo.git.custom_environment(**commit_env) if commit_env else nullcontext()
    )
    try:
        with env_context:
            repo.git.commit("-m", message)
    except GitCommandError as exc:
        raise RuntimeError(f"Git commit failed: {exc}") from exc

    return True


def _run_git_action_as_user(
    repo: Repo,
    project: Project,
    action: str,
    ref: Optional[str],
    *,
    clean: bool,
    user: object,
) -> str:
    linux_username = resolve_linux_username(user)
    if not linux_username:
        raise RuntimeError(
            f"Cannot determine Linux username for user {getattr(user, 'email', 'unknown')}"
        )
    workspace_dir = repo.working_tree_dir
    if not workspace_dir:
        raise RuntimeError("Repository working directory is not available.")

    repo_path = Path(workspace_dir)
    env = _build_user_git_env()

    def _git(args: list[str], *, timeout: float = 60.0) -> str:
        return _run_git_command_as_user(
            linux_username,
            repo_path,
            args,
            env=env,
            timeout=timeout,
        ).strip()

    remote = _select_remote(repo)
    target = ref or project.default_branch
    if not target:
        raise RuntimeError("No target branch specified for git action.")

    try:
        if action == "pull":
            messages: list[str] = []
            if clean:
                _git(["reset", "--hard", "HEAD"])
                messages.append("Executed: git reset --hard HEAD")
                _git(["clean", "-fd"])
                messages.append("Executed: git clean -fd")
            messages.append(f"Pulling {remote.name}/{target} …")
            pull_output = _git(["pull", remote.name, target], timeout=300.0)
            if pull_output:
                messages.append(pull_output)
            status_output = _git(["status", "--short", "--branch"])
            if status_output:
                messages.append("Working tree status:\n" + status_output)
            return "\n".join(messages)
        if action == "push":
            messages = [f"Pushing to {remote.name}/{target} …"]
            push_output = _git(["push", remote.name, target], timeout=300.0)
            messages.append(push_output or "Push completed.")
            return "\n".join(messages)
        if action == "status":
            return _git(["status", "--short", "--branch"])
    except SudoError as exc:
        raise RuntimeError(f"Git action failed: {exc}") from exc

    raise ValueError(f"Unsupported git action: {action}")


def run_git_action(
    project: Project,
    action: str,
    ref: Optional[str] = None,
    *,
    clean: bool = False,
    user: Optional[object] = None,
) -> str:
    repo = ensure_repo_checkout(project, user=user)
    if user is not None:
        return _run_git_action_as_user(
            repo,
            project,
            action,
            ref,
            clean=clean,
            user=user,
        )

    # Try CLI tools first if available (GitHub/GitLab with PAT)
    repo_path = Path(repo.working_tree_dir)
    if cli_git_service.supports_cli_git(project):
        try:
            if action == "pull":
                if clean:
                    log.info("Performing clean pull for project %s", project.name)
                    _discard_local_changes(repo)
                output = cli_git_service.pull_repo(project, repo_path)
                # Add status after pull
                status = repo.git.status("--short", "--branch").strip()
                if status:
                    output += "\nWorking tree status:\n" + status
                return output
            elif action == "push":
                return cli_git_service.push_repo(project, repo_path, branch=ref)
            elif action == "status":
                status_info = cli_git_service.get_repo_status(project, repo_path)
                return status_info.get("status_summary", "")
        except cli_git_service.CliGitServiceError as err:
            log.warning(
                "CLI git %s failed for %s, falling back to SSH: %s",
                action,
                project.name,
                err,
            )
            # Fall through to SSH-based operations

    # Fallback to SSH-based git operations
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
            env_context = (
                repo.git.custom_environment(**(env or {})) if env else nullcontext()
            )
            with env_context:
                pull_results = remote.pull(target)
            if pull_results:
                pull_messages: list[str] = []
                for pull_result in pull_results:
                    summary = getattr(pull_result, "summary", None) or getattr(
                        pull_result, "note", None
                    )
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
            env_context = (
                repo.git.custom_environment(**(env or {})) if env else nullcontext()
            )
            with env_context:
                push_results = remote.push(target)
            if push_results:
                push_messages: list[str] = []
                for push_result in push_results:
                    summary = getattr(push_result, "summary", None) or getattr(
                        push_result, "note", None
                    )
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
            if key_path and (
                "invalid format" in message or "permission denied" in message
            ):
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


def list_project_branches(
    project: Project, *, include_remote: bool = False, user: Optional[object] = None
) -> list[str]:
    repo = ensure_repo_checkout(project, user=user)
    branches: set[str] = set(head.name for head in repo.heads)
    if include_remote:
        for remote in repo.remotes:
            for ref in remote.refs:
                remote_head = getattr(ref, "remote_head", None)
                if remote_head:
                    branches.add(remote_head)
    default_branch = getattr(project, "default_branch", None)
    ordered = sorted(branches)
    if default_branch and default_branch in ordered:
        ordered.remove(default_branch)
        ordered.insert(0, default_branch)
    return ordered


def get_project_commit_history(
    project: Project, limit: int = 10, user: Optional[object] = None
) -> list[dict[str, Any]]:
    repo = ensure_repo_checkout(project, user=user)
    history: list[dict[str, Any]] = []
    try:
        commits = repo.iter_commits(max_count=limit)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Unable to read commit history: {exc}") from exc

    for commit in commits:
        committed_at = commit.committed_datetime
        if committed_at.tzinfo is None:
            committed_at = committed_at.replace(tzinfo=timezone.utc)
        history.append(
            {
                "hash": commit.hexsha,
                "short_hash": commit.hexsha[:7],
                "author": getattr(commit.author, "name", None) or "unknown",
                "email": getattr(commit.author, "email", None),
                "date": committed_at,
                "message": (commit.message or "").splitlines()[0],
            }
        )
    return history


def delete_project_branch(
    project: Project, branch: str, *, force: bool = False, user: Optional[object] = None
) -> None:
    branch = (branch or "").strip()
    if not branch:
        raise RuntimeError("Branch name is required.")
    repo = ensure_repo_checkout(project, user=user)
    default_branch = project.default_branch or "main"
    if branch == default_branch:
        raise RuntimeError("Cannot delete the default branch.")
    existing_branches = [head.name for head in repo.heads]
    if branch not in existing_branches:
        raise RuntimeError(f"Branch {branch} does not exist.")

    target_branch = (
        default_branch if default_branch in existing_branches else existing_branches[0]
    )
    env = build_project_git_env(project)
    context = repo.git.custom_environment(**env) if env else nullcontext()
    with context:
        current_branch = getattr(repo.head, "ref", None)
        if current_branch and current_branch.name == branch:
            repo.git.checkout(target_branch)
        try:
            repo.git.branch("-D" if force else "-d", branch)
        except GitCommandError as exc:
            raise RuntimeError(f"Failed to delete branch {branch}: {exc}") from exc


def checkout_or_create_branch(
    project: Project,
    branch: str,
    base: Optional[str] = None,
    user: Optional[object] = None,
) -> bool:
    branch = (branch or "").strip()
    if not branch:
        raise RuntimeError("Branch name is required.")
    repo = ensure_repo_checkout(project, user=user)
    env = build_project_git_env(project)
    context = repo.git.custom_environment(**env) if env else nullcontext()
    with context:
        repo.git.fetch("--all")
        existing_branches = [head.name for head in repo.heads]
        if branch in existing_branches:
            repo.git.checkout(branch)
            return False
        remote = _select_remote(repo)
        remote_ref = f"{remote.name}/{branch}"
        remote_names = [ref.name for ref in remote.refs]
        if remote_ref in remote_names:
            repo.git.checkout("-b", branch, remote_ref)
            return True
        base_branch = (base or project.default_branch or "").strip()
        if not base_branch:
            raise RuntimeError("Base branch could not be determined.")
        if base_branch not in existing_branches:
            try:
                repo.git.checkout(base_branch)
            except GitCommandError:
                repo.git.checkout("-b", base_branch, f"{remote.name}/{base_branch}")
        else:
            repo.git.checkout(base_branch)
        repo.git.checkout("-b", branch)
        return True


def merge_branch(
    project: Project,
    source_branch: str,
    target_branch: str,
    user: Optional[object] = None,
) -> None:
    source_branch = (source_branch or "").strip()
    target_branch = (target_branch or "").strip()
    if not source_branch or not target_branch:
        raise RuntimeError("Source and target branches are required.")
    repo = ensure_repo_checkout(project, user=user)
    env = build_project_git_env(project)
    context = repo.git.custom_environment(**env) if env else nullcontext()
    with context:
        repo.git.fetch("--all")
        repo.git.checkout(target_branch)
        try:
            repo.git.merge(source_branch)
        except GitCommandError as exc:
            raise RuntimeError(f"Merge failed: {exc}") from exc


def get_repo_status(project: Project, user: Optional[object] = None) -> dict[str, Any]:
    try:
        repo = ensure_repo_checkout(project, user=user)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Unable to inspect repository for project %s: %s", project.name, exc
        )
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
    else:
        # FETCH_HEAD doesn't exist - this is normal for freshly initialized workspaces
        last_pull_display = "Never pulled (workspace initialized)"

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
        "workspace_path": repo.working_dir,
    }
