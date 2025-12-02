from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from flask import current_app

# Legacy shared tmux socket directory - kept for backwards compatibility
# Set TMUX_USE_DEFAULT_SOCKET=false in .env to use this instead of default socket
TMUX_SOCKET_DIR = "/var/run/tmux-aiops"


def _use_default_socket() -> bool:
    """Check if we should use the default tmux socket location.

    When True (default), sessions appear in standard `tmux list-sessions`.
    When False, uses custom socket in TMUX_SOCKET_DIR for isolation.
    """
    try:
        config_value = current_app.config.get("TMUX_USE_DEFAULT_SOCKET", True)
        if isinstance(config_value, str):
            return config_value.lower() not in ("false", "0", "no")
        return bool(config_value)
    except RuntimeError:
        # Outside app context, default to True
        return True


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


def _get_socket_path(linux_username: str) -> Optional[str]:
    """Get the socket path for a user's tmux server.

    Returns None when using default socket (sessions visible in `tmux ls`).
    Returns custom path when TMUX_USE_DEFAULT_SOCKET is False.
    """
    if _use_default_socket():
        return None  # Use default tmux socket
    return f"{TMUX_SOCKET_DIR}/{linux_username}.sock"


def _run_tmux_as_user(
    linux_username: str, tmux_args: List[str], timeout: float = 5.0
) -> subprocess.CompletedProcess:
    """Run a tmux command as a specific user.

    Used when TMUX_USE_DEFAULT_SOCKET is True and we need to interact with
    another user's tmux server. The socket is in /tmp/tmux-{uid}/ and only
    accessible by that user.

    Args:
        linux_username: Linux username to run command as
        tmux_args: Arguments to pass to tmux (e.g., ["list-sessions"])
        timeout: Command timeout in seconds

    Returns:
        CompletedProcess result

    Raises:
        TmuxServiceError: If the command fails
    """
    from .sudo_service import run_as_user

    cmd = ["tmux"] + tmux_args
    try:
        return run_as_user(linux_username, cmd, timeout=timeout)
    except Exception as exc:
        raise TmuxServiceError(f"tmux command failed for user {linux_username}: {exc}") from exc


def _get_server(linux_username: Optional[str] = None):
    """Get tmux server for a specific Linux user.

    When TMUX_USE_DEFAULT_SOCKET is True (default):
        Uses the user's default tmux server (visible in `tmux ls`).
        NOTE: When linux_username differs from current user, libtmux cannot
        directly access the user's socket. Use _run_tmux_as_user() for operations
        that need to interact with another user's tmux server.

    When TMUX_USE_DEFAULT_SOCKET is False:
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
            if socket:
                # Use custom socket path for legacy mode
                return libtmux.Server(socket_path=socket)
            else:
                # Default socket mode - we can only use libtmux for current user
                # For other users, operations must use _run_tmux_as_user()
                current_user = os.environ.get("USER", "")
                if current_user and current_user != linux_username:
                    # Return a dummy server - callers should use _run_tmux_as_user() instead
                    # We still need to return something for backward compatibility
                    current_app.logger.debug(
                        "libtmux Server for user %s requested by %s - use _run_tmux_as_user() for operations",
                        linux_username,
                        current_user,
                    )
                return libtmux.Server()
        else:
            # Fallback to default server for syseng/system operations
            return libtmux.Server()
    except Exception as exc:  # pragma: no cover - backend error
        raise TmuxServiceError(f"Unable to initialize tmux server: {exc}") from exc


def _ensure_server_running(linux_username: str) -> None:
    """Ensure user's tmux server is running, start if needed.

    When TMUX_USE_DEFAULT_SOCKET is True (default):
        Uses the user's default tmux server. Sessions visible in `tmux ls`.
        Commands run as target user via sudo.

    When TMUX_USE_DEFAULT_SOCKET is False:
        Creates a new tmux server for the user if one isn't already running.
        The server runs as the target user via sudo, with socket in shared directory.

    Args:
        linux_username: Linux username to run tmux as
    """
    from .sudo_service import run_as_user

    socket_path = _get_socket_path(linux_username)

    if socket_path is None:
        # Default socket mode - check if user's default tmux server is running
        try:
            run_as_user(
                linux_username,
                ["tmux", "list-sessions"],
                timeout=5.0,
            )
            return  # Server already running
        except Exception:
            pass  # Server not running

        # Start new default tmux server as the target user
        try:
            run_as_user(
                linux_username,
                ["tmux", "new-session", "-d", "-s", "main"],
                timeout=10.0,
            )
            current_app.logger.info(
                "Started default tmux server for user %s", linux_username
            )
        except Exception as exc:
            raise TmuxServiceError(
                f"Unable to start tmux server for {linux_username}: {exc}"
            ) from exc
        return

    # Legacy custom socket mode
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


def get_user_socket_path(linux_username: str) -> Optional[str]:
    """Get the socket path for a user's tmux server (public API).

    Args:
        linux_username: Linux username

    Returns:
        Path to the user's tmux socket, or None if using default socket
    """
    return _get_socket_path(linux_username)


def _ensure_session(
    *,
    session_name: Optional[str] = None,
    create: bool = True,
    linux_username: Optional[str] = None,
):
    """Ensure a tmux session exists, optionally creating it.

    When linux_username is provided and using default sockets, this function
    uses subprocess calls via sudo to interact with the user's tmux server.

    Returns:
        Tuple of (session, session_was_just_created) where session_was_just_created
        is True if we just created the session (so the caller can reuse the default window).
    """
    resolved_name = _normalize_session_name(session_name)

    # Check if we're running as a different user than the target in default socket mode
    current_user = os.environ.get("USER", "")
    use_subprocess = (
        linux_username
        and _use_default_socket()
        and current_user
        and current_user != linux_username
    )

    if use_subprocess:
        # Use subprocess to interact with user's tmux server
        # Check if session exists
        session_exists = False
        try:
            result = _run_tmux_as_user(
                linux_username,
                ["has-session", "-t", resolved_name],
                timeout=5.0,
            )
            session_exists = result.returncode == 0
        except TmuxServiceError:
            pass  # Session doesn't exist

        session_just_created = False
        if not session_exists and create:
            # Create the session
            start_directory = current_app.config.get("TMUX_SHARED_SESSION_DIR")
            if not start_directory:
                start_directory = current_app.instance_path
            try:
                _run_tmux_as_user(
                    linux_username,
                    ["new-session", "-d", "-s", resolved_name, "-c", start_directory],
                    timeout=10.0,
                )
                # Disable mouse for cleaner operation
                try:
                    _run_tmux_as_user(
                        linux_username,
                        ["set-option", "-t", resolved_name, "mouse", "off"],
                        timeout=5.0,
                    )
                except TmuxServiceError:
                    pass  # Best effort
            except TmuxServiceError as exc:
                raise TmuxServiceError(
                    f"Unable to create tmux session {resolved_name!r}: {exc}"
                ) from exc
            session_exists = True
            session_just_created = True

        if session_exists:
            # Return a proxy object that has the methods we need
            return _TmuxSessionProxy(resolved_name, linux_username), session_just_created
        return None, False
    else:
        # Use libtmux for same-user or legacy mode
        server = _get_server(linux_username=linux_username)
        session = next(
            (item for item in server.sessions if item.get("session_name") == resolved_name),
            None,
        )
        session_just_created = False
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
            session_just_created = True
        return session, session_just_created


class _TmuxSessionProxy:
    """Proxy for tmux session operations when using subprocess for other users."""

    def __init__(self, session_name: str, linux_username: str):
        self._session_name = session_name
        self._linux_username = linux_username
        self._windows_cache: Optional[List["_TmuxWindowProxy"]] = None

    def get(self, key: str, default=None):
        if key == "session_name":
            return self._session_name
        return default

    @property
    def windows(self) -> List["_TmuxWindowProxy"]:
        """List windows in this session."""
        if self._windows_cache is not None:
            return self._windows_cache

        try:
            result = _run_tmux_as_user(
                self._linux_username,
                ["list-windows", "-t", self._session_name, "-F", "#{window_name}:#{window_id}:#{pane_id}"],
                timeout=5.0,
            )
            windows = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(":")
                    if len(parts) >= 3:
                        window_name = parts[0]
                        window_id = parts[1]
                        pane_id = parts[2]
                        windows.append(
                            _TmuxWindowProxy(
                                self._session_name,
                                window_name,
                                window_id,
                                pane_id,
                                self._linux_username,
                            )
                        )
            self._windows_cache = windows
            return windows
        except TmuxServiceError:
            return []

    def new_window(
        self,
        window_name: Optional[str] = None,
        attach: bool = False,
        start_directory: Optional[str] = None,
    ) -> "_TmuxWindowProxy":
        """Create a new window in this session."""
        cmd = ["new-window", "-t", self._session_name]
        if window_name:
            cmd.extend(["-n", window_name])
        if not attach:
            cmd.append("-d")
        if start_directory:
            cmd.extend(["-c", start_directory])

        try:
            _run_tmux_as_user(self._linux_username, cmd, timeout=10.0)
            # Invalidate cache
            self._windows_cache = None
            # Get the window info
            result = _run_tmux_as_user(
                self._linux_username,
                ["list-windows", "-t", self._session_name, "-F", "#{window_name}:#{window_id}:#{pane_id}"],
                timeout=5.0,
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(":")
                    if len(parts) >= 3 and parts[0] == window_name:
                        return _TmuxWindowProxy(
                            self._session_name,
                            parts[0],
                            parts[1],
                            parts[2],
                            self._linux_username,
                        )
            # If we can't find by name, return the last window
            if result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                last_line = lines[-1]
                parts = last_line.split(":")
                if len(parts) >= 3:
                    return _TmuxWindowProxy(
                        self._session_name,
                        parts[0],
                        parts[1],
                        parts[2],
                        self._linux_username,
                    )
        except TmuxServiceError as exc:
            raise TmuxServiceError(
                f"Unable to create window {window_name!r}: {exc}"
            ) from exc

        raise TmuxServiceError(f"Unable to create window {window_name!r}")

    def rename_first_window(
        self,
        new_name: str,
        start_directory: Optional[str] = None,
    ) -> "_TmuxWindowProxy":
        """Rename the first (default) window in this session and optionally change its directory.

        This is used when a session is first created to repurpose the default window
        instead of creating a new one.
        """
        # Get the first window
        windows = self.windows
        if not windows:
            raise TmuxServiceError("No windows in session to rename")

        first_window = windows[0]
        old_name = first_window.get("window_name")

        # Rename the window
        try:
            _run_tmux_as_user(
                self._linux_username,
                ["rename-window", "-t", f"{self._session_name}:{old_name}", new_name],
                timeout=5.0,
            )
        except TmuxServiceError as exc:
            raise TmuxServiceError(f"Unable to rename window: {exc}") from exc

        # Change directory if specified
        if start_directory:
            try:
                _run_tmux_as_user(
                    self._linux_username,
                    ["send-keys", "-t", f"{self._session_name}:{new_name}", f"cd {shlex.quote(start_directory)}", "Enter"],
                    timeout=5.0,
                )
            except TmuxServiceError:
                pass  # Best effort

        # Invalidate cache and return updated window proxy
        self._windows_cache = None

        # Get updated window info
        try:
            result = _run_tmux_as_user(
                self._linux_username,
                ["list-windows", "-t", self._session_name, "-F", "#{window_name}:#{window_id}:#{pane_id}"],
                timeout=5.0,
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(":")
                    if len(parts) >= 3 and parts[0] == new_name:
                        return _TmuxWindowProxy(
                            self._session_name,
                            parts[0],
                            parts[1],
                            parts[2],
                            self._linux_username,
                        )
        except TmuxServiceError:
            pass

        # Fallback: return proxy with the new name
        return _TmuxWindowProxy(
            self._session_name,
            new_name,
            first_window.get("window_id", ""),
            first_window.get("pane_id", ""),
            self._linux_username,
        )


class _TmuxWindowProxy:
    """Proxy for tmux window operations when using subprocess for other users."""

    def __init__(
        self,
        session_name: str,
        window_name: str,
        window_id: str,
        pane_id: str,
        linux_username: str,
    ):
        self._session_name = session_name
        self._window_name = window_name
        self._window_id = window_id
        self._pane_id = pane_id
        self._linux_username = linux_username

    def get(self, key: str, default=None):
        if key == "window_name":
            return self._window_name
        if key == "window_id":
            return self._window_id
        return default

    @property
    def panes(self) -> List["_TmuxPaneProxy"]:
        """List panes in this window."""
        return [_TmuxPaneProxy(self._target, self._pane_id, self._linux_username)]

    @property
    def attached_pane(self) -> Optional["_TmuxPaneProxy"]:
        """Get the active pane."""
        return _TmuxPaneProxy(self._target, self._pane_id, self._linux_username)

    @property
    def _target(self) -> str:
        return f"{self._session_name}:{self._window_name}"

    def select_window(self) -> None:
        """Select this window."""
        try:
            _run_tmux_as_user(
                self._linux_username,
                ["select-window", "-t", self._target],
                timeout=5.0,
            )
        except TmuxServiceError:
            pass  # Best effort

    def kill_window(self) -> None:
        """Kill this window."""
        _run_tmux_as_user(
            self._linux_username,
            ["kill-window", "-t", self._target],
            timeout=5.0,
        )

    def rename_window(self, new_name: str) -> None:
        """Rename this window."""
        _run_tmux_as_user(
            self._linux_username,
            ["rename-window", "-t", self._target, new_name],
            timeout=5.0,
        )
        self._window_name = new_name


class _TmuxPaneProxy:
    """Proxy for tmux pane operations when using subprocess for other users."""

    def __init__(self, target: str, pane_id: str, linux_username: str):
        self._target = target
        self._pane_id = pane_id
        self._linux_username = linux_username

    def send_keys(self, keys: str, enter: bool = True) -> None:
        """Send keys to this pane."""
        cmd = ["send-keys", "-t", self._target, keys]
        if enter:
            cmd.append("Enter")
        try:
            _run_tmux_as_user(self._linux_username, cmd, timeout=5.0)
        except TmuxServiceError as exc:
            current_app.logger.warning("Failed to send keys to %s: %s", self._target, exc)


def _rename_first_window(session, new_name: str, start_directory: Optional[str] = None):
    """Rename the first window in a session.

    Works with both our proxy objects and libtmux Session objects.
    Returns the renamed window or None if renaming failed.
    """
    # For our proxy class
    if hasattr(session, "rename_first_window"):
        return session.rename_first_window(new_name, start_directory)

    # For libtmux Session objects
    windows = session.windows
    if not windows:
        return None

    first_window = windows[0]
    try:
        first_window.rename_window(new_name)
        # Change directory if specified - send cd command to the pane
        if start_directory and hasattr(first_window, "attached_pane"):
            pane = first_window.attached_pane
            if pane:
                pane.send_keys(f"cd {shlex.quote(start_directory)}", enter=True)
        return first_window
    except Exception:
        return None


def ensure_project_window(
    project,
    *,
    window_name: Optional[str] = None,
    session_name: Optional[str] = None,
    linux_username: Optional[str] = None,
    user: Optional[object] = None,
    force_new: bool = False,
):
    session, session_just_created = _ensure_session(
        session_name=session_name, linux_username=linux_username
    )
    if session is None:
        raise TmuxServiceError("Unable to create shared tmux session.")
    base_window_name = window_name or _project_window_name(project)
    window_name = base_window_name
    created = False

    # Determine the start directory
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

    # If force_new is True, always create a new window with a unique suffix
    if force_new:
        import uuid
        suffix = uuid.uuid4().hex[:6]
        window_name = f"{base_window_name}-{suffix}"

        # If session was just created, rename the default window instead of creating new
        if session_just_created:
            try:
                window = _rename_first_window(session, window_name, start_directory)
                if window is not None:
                    created = True
                    return session, window, created
            except Exception:
                pass  # Fall through to create new window

        window = None  # Force creation
    else:
        window = next(
            (item for item in session.windows if item.get("window_name") == window_name),
            None,
        )

        # If session was just created and we're looking for a specific window name,
        # rename the default window to that name
        if window is None and session_just_created:
            try:
                window = _rename_first_window(session, window_name, start_directory)
                if window is not None:
                    created = True
                    return session, window, created
            except Exception:
                pass  # Fall through to create new window

    if window is None:
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
    # Handle both libtmux Window objects and our proxy
    if hasattr(window, "panes"):
        panes = len(window.panes)
    else:
        panes = 1
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
    skip_alias_filter: bool = False,
) -> List[TmuxWindow]:
    sessions: list = []
    if include_all_sessions:
        if linux_username is None:
            # When no specific user is specified, query one user's tmux server
            # All users in the aiops group see the same shared sessions via default socket
            try:
                server = _get_server(linux_username="michael")
                sessions = list(server.sessions)
            except Exception:
                # michael user doesn't have a server running, try syseng
                try:
                    server = _get_server(linux_username=None)
                    sessions = list(server.sessions)
                except Exception:
                    # No sessions available
                    sessions = []
        else:
            # Single user specified
            server = _get_server(linux_username=linux_username)
            sessions = list(server.sessions)
        with open("/tmp/tmux_debug.log", "a") as f:
            f.write(f"[list_windows] include_all_sessions={include_all_sessions}, linux_username={linux_username}, got {len(sessions)} sessions\n")
    else:
        session, _ = _ensure_session(
            session_name=session_name, create=False, linux_username=linux_username
        )
        if session is None:
            return []
        sessions = [session]
    if not sessions:
        return []

    # If skip_alias_filter is True, return all windows without name filtering
    if skip_alias_filter:
        windows_list = [
            _window_info(session, window)
            for session in sessions
            for window in session.windows
        ]
        return windows_list

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
    session, _ = _ensure_session(
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

    session, _ = _ensure_session(session_name=session_name, linux_username=linux_username)
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

    # Check if we need to use subprocess for another user
    current_user = os.environ.get("USER", "")
    use_subprocess = (
        linux_username
        and _use_default_socket()
        and current_user
        and current_user != linux_username
    )

    if use_subprocess:
        try:
            _run_tmux_as_user(
                linux_username,
                ["kill-window", "-t", target],
                timeout=5.0,
            )
        except TmuxServiceError as exc:
            raise TmuxServiceError(f"Unable to close tmux window {target}: {exc}") from exc
    else:
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
    # Check if we need to use subprocess for another user
    current_user = os.environ.get("USER", "")
    use_subprocess = (
        linux_username
        and _use_default_socket()
        and current_user
        and current_user != linux_username
    )

    if use_subprocess:
        try:
            result = _run_tmux_as_user(
                linux_username,
                ["list-panes", "-t", target, "-F", "#{pane_dead}"],
                timeout=5.0,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip() == "1"
        except TmuxServiceError:
            pass
        return False

    # Use socket path for per-user servers (only if not using default socket)
    cmd = ["tmux"]
    if linux_username:
        socket_path = _get_socket_path(linux_username)
        if socket_path:
            cmd.extend(["-S", socket_path])
    cmd.extend(["list-panes", "-t", target, "-F", "#{pane_dead}"])

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
    # Check if we need to use subprocess for another user
    current_user = os.environ.get("USER", "")
    use_subprocess = (
        linux_username
        and _use_default_socket()
        and current_user
        and current_user != linux_username
    )

    if use_subprocess:
        tmux_args = ["respawn-pane", "-k", "-t", target]
        if command:
            tmux_args.append(command)
        try:
            _run_tmux_as_user(linux_username, tmux_args, timeout=10.0)
            current_app.logger.info("Respawned pane %s", target)
        except TmuxServiceError as exc:
            raise TmuxServiceError(f"Failed to respawn pane {target}: {exc}") from exc
        return

    # Use socket path for per-user servers (only if not using default socket)
    cmd = ["tmux"]
    if linux_username:
        socket_path = _get_socket_path(linux_username)
        if socket_path:
            cmd.extend(["-S", socket_path])
    cmd.extend(["respawn-pane", "-k", "-t", target])

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
    """List sessions from all user tmux servers.

    When TMUX_USE_DEFAULT_SOCKET is True (default):
        Lists sessions from the default tmux server (current user only).
        For multi-user listing, callers should enumerate users and query each.

    When TMUX_USE_DEFAULT_SOCKET is False:
        Scans the shared socket directory for user socket files and lists
        all sessions across all running user tmux servers.

    Returns:
        List of dicts with owner, session, windows count, and socket path
    """
    import libtmux

    sessions = []

    if _use_default_socket():
        # Default socket mode - list from default tmux server
        try:
            server = libtmux.Server()
            for session in server.sessions:
                sessions.append({
                    "owner": os.environ.get("USER", "unknown"),
                    "session": session.get("session_name"),
                    "windows": len(session.windows),
                    "socket": "default",
                })
        except Exception:
            pass
        return sessions

    # Legacy mode - scan shared socket directory
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
