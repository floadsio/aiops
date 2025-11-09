from __future__ import annotations

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


_SLUG_REPLACEMENTS = str.maketrans({c: "-" for c in " ./\\:"})


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


def _get_server():
    try:
        import libtmux
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise TmuxServiceError("libtmux is required for tmux integrations.") from exc

    try:
        return libtmux.Server()
    except Exception as exc:  # pragma: no cover - backend error
        raise TmuxServiceError(f"Unable to initialize tmux server: {exc}") from exc


def _ensure_session(*, session_name: Optional[str] = None, create: bool = True):
    server = _get_server()
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
            raise TmuxServiceError(f"Unable to create tmux session {resolved_name!r}: {exc}") from exc
        try:
            session.set_option("mouse", "off")
        except Exception:  # noqa: BLE001 - best effort
            current_app.logger.debug("Unable to set tmux session options for %s", resolved_name)
    return session


def ensure_project_window(
    project,
    *,
    window_name: Optional[str] = None,
    session_name: Optional[str] = None,
):
    session = _ensure_session(session_name=session_name)
    if session is None:
        raise TmuxServiceError("Unable to create shared tmux session.")
    window_name = window_name or _project_window_name(project)
    created = False
    window = next(
        (item for item in session.windows if item.get("window_name") == window_name),
        None,
    )
    if window is None:
        start_directory = getattr(project, "local_path", None) or current_app.instance_path
        try:
            window = session.new_window(
                window_name=window_name,
                attach=False,
                start_directory=start_directory,
            )
        except Exception as exc:
            raise TmuxServiceError(f"Unable to create tmux window {window_name!r}: {exc}") from exc
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
) -> List[TmuxWindow]:
    sessions: list = []
    if include_all_sessions:
        server = _get_server()
        sessions = list(server.sessions)
    else:
        session = _ensure_session(session_name=session_name, create=False)
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


def get_or_create_window_for_project(project, *, session_name: Optional[str] = None) -> TmuxWindow:
    session, window, _ = ensure_project_window(project, session_name=session_name)
    return _window_info(session, window)


def find_window_for_project(project, *, session_name: Optional[str] = None) -> Optional[TmuxWindow]:
    session = _ensure_session(session_name=session_name, create=False)
    if session is None:
        return None
    window = next(
        (item for item in session.windows if item.get("window_name") == _project_window_name(project)),
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


def sync_project_windows(projects: Sequence[object], *, session_name: Optional[str] = None) -> TmuxSyncResult:
    """
    Ensure every project has a tmux window and prune orphaned project windows.
    """

    session = _ensure_session(session_name=session_name)
    existing = {window.get("window_name"): window for window in session.windows}

    desired_names: set[str] = set()
    created = 0
    for project in projects:
        window_name = _project_window_name(project)
        desired_names.add(window_name)
        if window_name not in existing:
            try:
                ensure_project_window(project, window_name=window_name, session_name=session_name)
            except TmuxServiceError:
                raise
            except Exception as exc:  # pragma: no cover - libtmux raise
                raise TmuxServiceError(f"Unable to create tmux window {window_name}: {exc}") from exc
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
            current_app.logger.warning("Unable to remove tmux window %s: %s", window_name, exc)
        else:
            removed += 1

    return TmuxSyncResult(created=created, removed=removed, total_managed=len(desired_names))


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
]
