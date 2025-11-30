from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from flask import current_app

# Shared tmux socket directory - created by install-service.sh with group perms
TMUX_SOCKET_DIR = "/var/run/tmux-aiops"


@dataclass(frozen=True)
class TmuxWindow:
    session_name: str
    window_name: str
    panes: int
    created: Optional[datetime] = None

    @property
    def target(self) -> str:
        return f"{self.session_name}:{self.window_name}"


class TmuxServiceError(RuntimeError):
    """Raised when tmux operations fail."""


@dataclass(frozen=True)
class TmuxSyncResult:
    created: int
    removed: int
    total_managed: int


_SLUG_REPLACEMENTS = str.maketrans({c: "-" for c in " ./\\:@"})


def _slugify(value: str) -> str:
    slug = value.lower().translate(_SLUG_REPLACEMENTS)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or "session"


def _default_session_name() -> str:
    return current_app.config.get("TMUX_SHARED_SESSION_NAME", "aiops")


def _normalize_session_name(session_name: Optional[str]) -> str:
    base = session_name or _default_session_name()
    slug = _slugify(str(base))
    return slug or "session"


def _first_token(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    return stripped.split()[0]


def session_name_for_user(user: Optional[object]) -> str:
    """
    Derive a tmux session name for the given user object.

    We favor the user's configured name, then username/email, falling back to an ID.
    """
    if user is not None:
        linux_username = getattr(user, "linux_username", None)
        if not linux_username:
            try:
                from .linux_users import resolve_linux_username
            except Exception:  # pragma: no cover - import errors handled elsewhere
                pass
            else:
                try:
                    linux_username = resolve_linux_username(user)
                except Exception:  # pragma: no cover - best effort resolution
                    linux_username = None
        if linux_username:
            return _normalize_session_name(str(linux_username))

        name = getattr(user, "name", None)
        if name:
            short_name = _first_token(str(name))
            if short_name:
                return _normalize_session_name(short_name)

        for attr in ("username", "email"):
            value = getattr(user, attr, None)
            if value:
                return _normalize_session_name(str(value))
        identifier = getattr(user, "id", None)
        if identifier is not None:
            return _normalize_session_name(str(identifier))
    return _normalize_session_name(None)


def _project_window_name(project) -> str:
    project_name = _slugify(getattr(project, "name", "") or "")
    project_id = getattr(project, "id", None)
    suffix = ""
    if project_id is not None:
        suffix = f"-p{project_id}"
    if project_name:
        return f"{project_name}{suffix}"
    if suffix:
        return f"project{suffix}"
    local_path = getattr(project, "local_path", "")
    slug_path = _slugify(local_path or "")
    if slug_path:
        return f"{slug_path}{suffix}"
    return f"project{suffix}"


def _get_socket_path(linux_username: str) -> str:
    """Get the socket path for a user's tmux server."""
    return f"{TMUX_SOCKET_DIR}/{linux_username}.sock"


def _get_server(linux_username: Optional[str] = None):
    """Get tmux server for a specific Linux user.

    Each user has their own tmux server with socket in shared directory.
    This enables sessions to run as the target user without sudo wrapping.

    Args:
        linux_username: Linux username for the tmux server. If None, uses default server.

    Returns:
        libtmux.Server instance for the user's tmux server
    """
    try:
        import libtmux
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise TmuxServiceError("libtmux is required for tmux integrations.") from exc

    try:
        if linux_username:
            socket = _get_socket_path(linux_username)
            # Use socket_path (not socket_name) for absolute paths
            return libtmux.Server(socket_path=socket)
        else:
            # Fallback to default server for syseng/system operations
            return libtmux.Server()
    except Exception as exc:  # pragma: no cover - backend error
        raise TmuxServiceError(f"Unable to initialize tmux server: {exc}") from exc


def _ensure_server_running(linux_username: str) -> None:
    """Ensure user's tmux server is running, start if needed.

    Creates a new tmux server for the user if one isn't already running.
    The server runs as the target user via sudo, with socket in shared directory.

    Args:
        linux_username: Linux username to run tmux as
    """
    from .sudo_service import run_as_user

    socket_path = _get_socket_path(linux_username)

    # Check if server is already running by trying to list sessions
    # Must run as target user since syseng may not have access to the socket yet
    try:
        run_as_user(
            linux_username,
            ["tmux", "-S", socket_path, "list-sessions"],
            timeout=5.0,
        )
        return  # Server already running
    except Exception:
        pass  # Server not running or socket doesn't exist

    # Start new server as the target user
    try:
        run_as_user(
            linux_username,
            ["tmux", "-S", socket_path, "new-session", "-d", "-s", "main"],
            timeout=10.0,
        )
        # Set socket group to 'aiops' so syseng (Flask) can access it
        # Both the user and syseng must be in the 'aiops' group
        try:
            subprocess.run(
                ["sudo", "chown", f"{linux_username}:aiops", socket_path],
                capture_output=True,
                timeout=5,
                check=True,
            )
        except Exception as chown_exc:
            current_app.logger.warning(
                "Failed to set socket group for %s: %s", socket_path, chown_exc
            )
        # Set socket permissions for group access
        try:
            run_as_user(
                linux_username,
                ["chmod", "770", socket_path],
                timeout=5.0,
            )
        except Exception as chmod_exc:
            current_app.logger.warning(
                "Failed to set socket permissions for %s: %s", socket_path, chmod_exc
            )
        # Also grant access via tmux server-access (belt and suspenders for tmux 3.3+)
        try:
            run_as_user(
                linux_username,
                ["tmux", "-S", socket_path, "server-access", "-a", "syseng"],
                timeout=5.0,
            )
        except Exception as access_exc:
            current_app.logger.warning(
                "Failed to grant syseng access to tmux server %s: %s",
                socket_path,
                access_exc,
            )
        current_app.logger.info(
            "Started tmux server for user %s at %s", linux_username, socket_path
        )
    except Exception as exc:
        raise TmuxServiceError(
            f"Unable to start tmux server for {linux_username}: {exc}"
        ) from exc


def get_user_socket_path(linux_username: str) -> str:
    """Get the socket path for a user's tmux server (public API).

    Args:
        linux_username: Linux username

    Returns:
        Path to the user's tmux socket
    """
    return _get_socket_path(linux_username)


def _ensure_session(
    *,
    session_name: Optional[str] = None,
    create: bool = True,
    linux_username: Optional[str] = None,
):
    # Ensure user's tmux server is running before trying to connect
    if linux_username:
        _ensure_server_running(linux_username)

    server = _get_server(linux_username=linux_username)
    resolved_name = _normalize_session_name(session_name)
    session = next(
        (item for item in server.sessions if item.get("session_name") == resolved_name),
        None,
    )
    if session is None and create:
        start_directory = current_app.config.get("TMUX_SHARED_SESSION_DIR")
        if not start_directory:
            start_directory = current_app.instance_path
        try:
            session = server.new_session(
                session_name=resolved_name,
                start_directory=start_directory,
                attach=False,
            )
        except Exception as exc:
            raise TmuxServiceError(
                f"Unable to create tmux session {resolved_name!r}: {exc}"
            ) from exc
        try:
            session.set_option("mouse", "off")
        except Exception:  # noqa: BLE001 - best effort
            current_app.logger.debug(
                "Unable to set tmux session options for %s", resolved_name
            )
    return session


def ensure_project_window(
    project,
    *,
    window_name: Optional[str] = None,
    session_name: Optional[str] = None,
    linux_username: Optional[str] = None,
    user: Optional[object] = None,
):
    session = _ensure_session(session_name=session_name, linux_username=linux_username)
    if session is None:
        raise TmuxServiceError("Unable to create shared tmux session.")
    window_name = window_name or _project_window_name(project)
    created = False
    window = next(
        (item for item in session.windows if item.get("window_name") == window_name),
        None,
    )
    if window is None:
        # Use workspace path if user is provided, otherwise fall back to instance path
        start_directory = current_app.instance_path
        if user is not None:
            from .workspace_service import get_workspace_path

            workspace_path = get_workspace_path(project, user)
            if workspace_path is not None:
                start_directory = str(workspace_path)
                # Create workspace directory if it doesn't exist
                try:
                    workspace_path.mkdir(parents=True, exist_ok=True)
                except OSError:
                    current_app.logger.warning(
                        "Unable to create workspace directory %s", workspace_path
                    )
        try:
            window = session.new_window(
                window_name=window_name,
                attach=False,
                start_directory=start_directory,
            )
        except Exception as exc:
            raise TmuxServiceError(
                f"Unable to create tmux window {window_name!r}: {exc}"
            ) from exc
        created = True
    return session, window, created


def _window_info(session, window) -> TmuxWindow:
    window_name = window.get("window_name")
    panes = len(window.panes)
    created_raw = window.get("window_created")
    created: Optional[datetime] = None
    if created_raw:
        try:
            created = datetime.fromtimestamp(int(created_raw), tz=timezone.utc)
        except (ValueError, OSError):
            created = None
    return TmuxWindow(
        session_name=session.get("session_name"),
        window_name=window_name,
        panes=panes,
        created=created,
    )


def list_windows_for_aliases(
    tenant_name: str,
    project_local_path: Optional[str] = None,
    *,
    extra_aliases: Optional[Iterable[str]] = None,
    session_name: Optional[str] = None,
    include_all_sessions: bool = False,
    linux_username: Optional[str] = None,
) -> List[TmuxWindow]:
    sessions: list = []
    if include_all_sessions:
        server = _get_server(linux_username=linux_username)
        sessions = list(server.sessions)
    else:
        session = _ensure_session(
            session_name=session_name, create=False, linux_username=linux_username
        )
        if session is None:
            return []
        sessions = [session]
    if not sessions:
        return []

    aliases: set[str] = set()
    if tenant_name:
        aliases.add(_slugify(tenant_name))
    if project_local_path:
        aliases.add(_slugify(project_local_path))
    if extra_aliases:
        aliases.update(_slugify(alias) for alias in extra_aliases if alias)

    if not aliases:
        return [
            _window_info(session, window)
            for session in sessions
            for window in session.windows
        ]

    matches: List[TmuxWindow] = []
    for session in sessions:
        for window in session.windows:
            name = window.get("window_name", "").lower()
            if any(alias for alias in aliases if alias and alias in name):
                matches.append(_window_info(session, window))
    return matches


def get_or_create_window_for_project(
    project,
    *,
    session_name: Optional[str] = None,
    linux_username: Optional[str] = None,
    user: Optional[object] = None,
) -> TmuxWindow:
    session, window, _ = ensure_project_window(
        project,
        session_name=session_name,
        linux_username=linux_username,
        user=user,
    )
    return _window_info(session, window)


def find_window_for_project(
    project,
    *,
    session_name: Optional[str] = None,
    linux_username: Optional[str] = None,
) -> Optional[TmuxWindow]:
    session = _ensure_session(
        session_name=session_name, create=False, linux_username=linux_username
    )
    if session is None:
        return None
    window = next(
        (
            item
            for item in session.windows
            if item.get("window_name") == _project_window_name(project)
        ),
        None,
    )
    if window is None:
        return None
    return _window_info(session, window)


def _is_managed_window_name(window_name: str) -> bool:
    if "-p" not in window_name:
        return False
    _, _, suffix = window_name.rpartition("-p")
    if not suffix:
        return False
    try:
        int(suffix)
    except ValueError:
        return False
    return True


def sync_project_windows(
    projects: Sequence[object],
    *,
    session_name: Optional[str] = None,
    linux_username: Optional[str] = None,
) -> TmuxSyncResult:
    """
    Ensure every project has a tmux window and prune orphaned project windows.
    """

    session = _ensure_session(session_name=session_name, linux_username=linux_username)
    existing = {window.get("window_name"): window for window in session.windows}

    desired_names: set[str] = set()
    created = 0
    for project in projects:
        window_name = _project_window_name(project)
        desired_names.add(window_name)
        if window_name not in existing:
            try:
                ensure_project_window(
                    project,
                    window_name=window_name,
                    session_name=session_name,
                    linux_username=linux_username,
                )
            except TmuxServiceError:
                raise
            except Exception as exc:  # pragma: no cover - libtmux raise
                raise TmuxServiceError(
                    f"Unable to create tmux window {window_name}: {exc}"
                ) from exc
            created += 1

    removed = 0
    for window_name, window in existing.items():
        if window_name in desired_names:
            continue
        if not _is_managed_window_name(window_name):
            continue
        try:
            window.kill_window()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            current_app.logger.warning(
                "Unable to remove tmux window %s: %s", window_name, exc
            )
        else:
            removed += 1

    return TmuxSyncResult(
        created=created, removed=removed, total_managed=len(desired_names)
    )


def close_tmux_target(target: str, *, linux_username: Optional[str] = None) -> None:
    """
    Close a tmux window given a session:window target string.
    """
    if not target or ":" not in target:
        raise TmuxServiceError("Invalid tmux target.")
    session_name, _, window_name = target.partition(":")
    server = _get_server(linux_username=linux_username)
    session = next(
        (item for item in server.sessions if item.get("session_name") == session_name),
        None,
    )
    if session is None:
        raise TmuxServiceError(f"Session {session_name!r} not found.")
    window = next(
        (item for item in session.windows if item.get("window_name") == window_name),
        None,
    )
    if window is None:
        raise TmuxServiceError(
            f"Window {window_name!r} not found in session {session_name!r}."
        )
    try:
        window.kill_window()
    except Exception as exc:  # noqa: BLE001 - best effort
        raise TmuxServiceError(f"Unable to close tmux window {target}: {exc}") from exc


def is_pane_dead(target: str, linux_username: str | None = None) -> bool:
    """Check if a tmux pane is dead.

    Args:
        target: Tmux target (session:window or session:window.pane format)
        linux_username: Linux username for per-user tmux server (uses socket path)

    Returns:
        True if the pane is dead, False if it's alive or doesn't exist
    """
    # Use socket path for per-user servers
    if linux_username:
        socket_path = _get_socket_path(linux_username)
        cmd = ["tmux", "-S", socket_path, "list-panes", "-t", target, "-F", "#{pane_dead}"]
    else:
        cmd = ["tmux", "list-panes", "-t", target, "-F", "#{pane_dead}"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Output is "1" if dead, "0" if alive
            return result.stdout.strip() == "1"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


def respawn_pane(
    target: str,
    command: str | None = None,
    linux_username: str | None = None,
) -> None:
    """Respawn a dead tmux pane with the original or new command.

    Args:
        target: Tmux target (session:window or session:window.pane format)
        command: Optional new command to run (None = use original command)
        linux_username: Linux username for per-user tmux server (uses socket path)

    Raises:
        TmuxServiceError: If respawn fails
    """
    # Use socket path for per-user servers
    if linux_username:
        socket_path = _get_socket_path(linux_username)
        cmd = ["tmux", "-S", socket_path, "respawn-pane", "-k", "-t", target]
    else:
        cmd = ["tmux", "respawn-pane", "-k", "-t", target]

    if command:
        cmd.append(command)

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        current_app.logger.info("Respawned pane %s", target)
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.strip() if exc.stderr else str(exc)
        raise TmuxServiceError(f"Failed to respawn pane {target}: {error_msg}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TmuxServiceError(f"Timeout respawning pane {target}") from exc


def list_all_user_sessions() -> list[dict]:
    """List sessions from all user tmux servers in the shared socket directory.

    Scans the shared socket directory for user socket files and lists
    all sessions across all running user tmux servers.

    Returns:
        List of dicts with owner, session, windows count, and socket path
    """
    import libtmux

    sessions = []
    socket_dir = Path(TMUX_SOCKET_DIR)

    if not socket_dir.exists():
        return sessions

    for socket_file in socket_dir.glob("*.sock"):
        username = socket_file.stem
        try:
            server = libtmux.Server(socket_name=str(socket_file))
            for session in server.sessions:
                sessions.append({
                    "owner": username,
                    "session": session.get("session_name"),
                    "windows": len(session.windows),
                    "socket": str(socket_file),
                })
        except Exception:
            # Server not running or socket stale
            continue

    return sessions


__all__ = [
    "TmuxWindow",
    "TmuxServiceError",
    "TMUX_SOCKET_DIR",
    "ensure_project_window",
    "get_or_create_window_for_project",
    "find_window_for_project",
    "list_windows_for_aliases",
    "sync_project_windows",
    "TmuxSyncResult",
    "session_name_for_user",
    "close_tmux_target",
    "is_pane_dead",
    "respawn_pane",
    "list_all_user_sessions",
    "get_user_socket_path",
]
