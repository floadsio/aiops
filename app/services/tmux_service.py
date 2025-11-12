from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

from flask import current_app


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


def session_name_for_user(user: Optional[object]) -> str:
    """
    Derive a tmux session name for the given user object.

    We favor the user's configured name, then username/email, falling back to an ID.
    """
    if user is not None:
        for attr in ("name", "username", "email"):
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


def _get_server(linux_username: Optional[str] = None):
    try:
        import libtmux
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise TmuxServiceError("libtmux is required for tmux integrations.") from exc

    socket_path = None
    target_linux_username = None
    if linux_username:
        from .linux_users import get_linux_user_info
        user_info = get_linux_user_info(linux_username)
        if user_info:
            socket_path = f"/tmp/tmux-{user_info.uid}/default"
            target_linux_username = linux_username
            current_app.logger.debug(
                "Using tmux socket for user %s: %s", linux_username, socket_path
            )

    try:
        if socket_path and target_linux_username:
            # When accessing another user's tmux session, we need to run tmux
            # commands as that user via sudo to bypass tmux's ownership checks
            return _SudoAwareServer(
                socket_path=socket_path, sudo_username=target_linux_username
            )
        elif socket_path:
            return libtmux.Server(socket_path=socket_path)
        return libtmux.Server()
    except Exception as exc:  # pragma: no cover - backend error
        raise TmuxServiceError(f"Unable to initialize tmux server: {exc}") from exc


class _SudoAwareSession:
    """A session proxy that routes all operations through a sudo-aware server."""

    def __init__(self, session_name: str, server):
        self.session_name = session_name
        self.server = server

    def get(self, key: str, default=None):
        """Get session metadata via tmux command."""
        if key == "session_name":
            return self.session_name
        # For other attributes, query tmux
        result = self.server._run_tmux_cmd(
            "display-message",
            f"-t{self.session_name}",
            f"#{{session_{key}}}",
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout[0]
        return default

    @property
    def windows(self):
        """List windows in this session via sudo."""
        result = self.server._run_tmux_cmd(
            "list-windows",
            f"-t{self.session_name}",
            "-F#{window_id}\t#{window_name}\t#{window_created}",
        )
        windows = []
        for line in result.stdout:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 2)
            if len(parts) >= 2:
                window_id, window_name = parts[0], parts[1]
                created = parts[2] if len(parts) > 2 else None
                window = _SudoAwareWindow(
                    window_id=window_id,
                    window_name=window_name,
                    window_created=created,
                    session=self,
                )
                windows.append(window)
        return windows

    def set_option(self, name: str, value):
        """Set session option via sudo."""
        result = self.server.cmd("set-option", "-s", "-t", self.session_name, name, value)
        if result.returncode != 0:
            raise TmuxServiceError(
                f"Unable to set option {name} on session {self.session_name}: {result.stderr}"
            )

    def new_window(self, window_name: str, start_directory: Optional[str] = None, attach: bool = False, **kwargs):
        """Create new window in this session via sudo."""
        args = ["-n", window_name]
        if start_directory:
            args.extend(["-c", start_directory])
        if attach:
            args.append("")  # Attach flag

        result = self.server.cmd("new-window", f"-t{self.session_name}", *args)
        if result.returncode != 0:
            raise TmuxServiceError(
                f"Unable to create window {window_name} in session {self.session_name}: {result.stderr}"
            )

        # Return a window proxy
        return _SudoAwareWindow(
            window_id="",
            window_name=window_name,
            window_created=None,
            session=self,
        )

    def select_window(self):
        """Select this session (for compatibility)."""
        pass


class _SudoAwareWindow:
    """A window proxy that routes all operations through a sudo-aware session."""

    def __init__(self, window_id: str, window_name: str, window_created: Optional[str], session):
        self.window_id = window_id
        self.window_name = window_name
        self.window_created = window_created
        self.session = session
        self._panes = None

    def get(self, key: str, default=None):
        """Get window metadata."""
        if key == "window_name":
            return self.window_name
        if key == "window_id":
            return self.window_id
        if key == "window_created":
            return self.window_created
        return default

    @property
    def panes(self):
        """List panes in this window via sudo."""
        if self._panes is None:
            result = self.session.server._run_tmux_cmd(
                "list-panes",
                f"-t{self.session.session_name}:{self.window_name}",
                "-F#{pane_id}\t#{pane_index}",
            )
            self._panes = []
            for line in result.stdout:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) >= 1:
                    pane_id = parts[0]
                    pane_index = parts[1] if len(parts) > 1 else "0"
                    pane = _SudoAwarePane(
                        pane_id=pane_id,
                        pane_index=pane_index,
                        window=self,
                    )
                    self._panes.append(pane)
        return self._panes

    @property
    def attached_pane(self):
        """Get the attached pane (first pane for now)."""
        panes = self.panes
        return panes[0] if panes else None

    def select_window(self):
        """Select this window."""
        result = self.session.server.cmd(
            "select-window",
            f"-t{self.session.session_name}:{self.window_name}",
        )
        if result.returncode != 0:
            raise TmuxServiceError(
                f"Unable to select window {self.window_name}: {result.stderr}"
            )

    def split_window(self, *args, **kwargs):
        """Split window (stub for compatibility)."""
        pass


class _SudoAwarePane:
    """A pane proxy that routes all operations through a sudo-aware window."""

    def __init__(self, pane_id: str, pane_index: str, window):
        self.pane_id = pane_id
        self.pane_index = pane_index
        self.window = window

    def get(self, key: str, default=None):
        """Get pane metadata."""
        if key == "pane_id":
            return self.pane_id
        if key == "pane_index":
            return self.pane_index
        return default

    def send_keys(self, *args, **kwargs):
        """Send keys to this pane via sudo."""
        # Handle the 'enter' parameter
        enter = kwargs.pop("enter", False)

        # Build the command
        target = f"{self.window.session.session_name}:{self.window.window_name}.{self.pane_index}"
        tmux_args = ["send-keys", "-t", target]

        # Add the keys (args)
        tmux_args.extend(args)

        # Add Enter key if requested
        if enter:
            tmux_args.append("Enter")

        result = self.window.session.server.cmd(*tmux_args)
        if result.returncode != 0:
            raise TmuxServiceError(
                f"Unable to send keys to pane {self.pane_id}: {result.stderr}"
            )
        return result


class _SudoAwareServer:
    """A tmux Server that runs commands via sudo to bypass tmux ownership checks.

    Even with proper file permissions, tmux has internal ownership checks that
    prevent one user from accessing another user's sessions directly. This class
    wraps libtmux and executes tmux commands as the target user via sudo to
    work around this limitation.
    """

    def __init__(self, socket_path: str, sudo_username: str, **kwargs):
        import libtmux

        # Store configuration
        self.sudo_username = sudo_username
        self.socket_path = socket_path
        self.socket_name = kwargs.get("socket_name")
        self.config_file = kwargs.get("config_file")
        self.colors = kwargs.get("colors")

        # Create a base server instance for reference (may not work directly
        # due to ownership checks, but we keep it for compatibility)
        try:
            self._base_server = libtmux.Server(socket_path=socket_path, **kwargs)
        except Exception:
            # If direct connection fails, we'll handle it via sudo
            self._base_server = None

    def __getattr__(self, name: str):
        """Delegate attribute access to the base server if available."""
        if self._base_server is not None:
            return getattr(self._base_server, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    @property
    def sessions(self):
        """List sessions by running 'tmux list-sessions' via sudo."""
        result = self._run_tmux_cmd("list-sessions", "-F#{session_id}\t#{session_name}")
        sessions = []

        for line in result.stdout:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                session_id, session_name = parts
                # Create a sudo-aware session proxy
                session = _SudoAwareSession(
                    session_name=session_name,
                    server=self,
                )
                sessions.append(session)

        return sessions

    def cmd(self, cmd: str, *args, target: Optional[str] = None):
        """Execute tmux command via sudo."""
        svr_args = [cmd]
        if self.socket_name:
            svr_args.insert(0, f"-L{self.socket_name}")
        if self.socket_path:
            svr_args.insert(0, f"-S{self.socket_path}")
        if self.config_file:
            svr_args.insert(0, f"-f{self.config_file}")
        if self.colors:
            if self.colors == 256:
                svr_args.insert(0, "-2")
            elif self.colors == 88:
                svr_args.insert(0, "-8")

        cmd_args = ["-t", str(target), *args] if target is not None else [*args]
        return self._run_tmux_cmd(*svr_args, *cmd_args)

    def _run_tmux_cmd(self, *args):
        """Execute a tmux command via sudo as the target user."""
        import libtmux.common

        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise TmuxServiceError("tmux binary not found")

        # Build command: sudo -u <user> tmux <args>
        full_cmd = ["sudo", "-u", self.sudo_username, tmux_bin] + [str(a) for a in args]

        current_app.logger.debug("Executing tmux via sudo: %s", " ".join(full_cmd))

        try:
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="backslashreplace",
            )
            stdout, stderr = process.communicate()
            returncode = process.returncode
        except Exception:
            current_app.logger.exception("Exception executing tmux command via sudo")
            raise

        # Parse output similar to libtmux.common.tmux_cmd
        stdout_split = stdout.split("\n") if stdout else []
        while stdout_split and stdout_split[-1] == "":
            stdout_split.pop()

        stderr_split = stderr.split("\n") if stderr else []
        stderr_list = list(filter(None, stderr_split))

        # Create a result object that mimics tmux_cmd
        result = libtmux.common.tmux_cmd(*args)
        result.returncode = returncode
        result.stdout = stdout_split
        result.stderr = stderr_list

        if returncode != 0 and stderr_list:
            current_app.logger.debug(
                "tmux command stderr: %s", stderr_list
            )

        return result

    def new_session(
        self,
        session_name: str,
        start_directory: Optional[str] = None,
        attach: bool = False,
        **kwargs,
    ):
        """Create a new tmux session via sudo."""
        args = ["-d", "-s", session_name]
        if start_directory:
            args.extend(["-c", start_directory])
        if attach:
            # Remove -d flag if attaching
            args = [a for a in args if a != "-d"]

        # Add any additional kwargs
        for key, value in kwargs.items():
            if value is not None and value is not False:
                args.append(f"-{key}={value}")

        result = self.cmd("new-session", *args)

        if result.returncode != 0:
            raise TmuxServiceError(
                f"Unable to create tmux session {session_name!r}: {result.stderr}"
            )

        # Return a sudo-aware session proxy
        return _SudoAwareSession(session_name=session_name, server=self)


def _ensure_session(
    *,
    session_name: Optional[str] = None,
    create: bool = True,
    linux_username: Optional[str] = None,
):
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
):
    session = _ensure_session(
        session_name=session_name, linux_username=linux_username
    )
    if session is None:
        raise TmuxServiceError("Unable to create shared tmux session.")
    window_name = window_name or _project_window_name(project)
    created = False
    window = next(
        (item for item in session.windows if item.get("window_name") == window_name),
        None,
    )
    if window is None:
        start_directory = (
            getattr(project, "local_path", None) or current_app.instance_path
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
) -> TmuxWindow:
    session, window, _ = ensure_project_window(
        project, session_name=session_name, linux_username=linux_username
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


__all__ = [
    "TmuxWindow",
    "TmuxServiceError",
    "ensure_project_window",
    "get_or_create_window_for_project",
    "find_window_for_project",
    "list_windows_for_aliases",
    "sync_project_windows",
    "TmuxSyncResult",
    "session_name_for_user",
    "close_tmux_target",
]
