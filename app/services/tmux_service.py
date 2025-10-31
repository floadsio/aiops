from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional

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


_SLUG_REPLACEMENTS = str.maketrans({c: "-" for c in " ./\\:"})


def _slugify(value: str) -> str:
    slug = value.lower().translate(_SLUG_REPLACEMENTS)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or "session"


def _shared_session_name() -> str:
    return current_app.config.get("TMUX_SHARED_SESSION_NAME", "aiops")


def _project_window_name(project) -> str:
    tenant = getattr(project, "tenant", None)
    tenant_part = _slugify(getattr(tenant, "name", "") or "")
    project_part = _slugify(getattr(project, "name", "") or f"project-{project.id}")
    if tenant_part:
        return f"{tenant_part}-{project_part}"
    return project_part


def _get_server():
    try:
        import libtmux
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise TmuxServiceError("libtmux is required for tmux integrations.") from exc

    try:
        return libtmux.Server()
    except Exception as exc:  # pragma: no cover - backend error
        raise TmuxServiceError(f"Unable to initialize tmux server: {exc}") from exc


def _ensure_shared_session(create: bool = True):
    server = _get_server()
    session_name = _shared_session_name()
    session = next(
        (item for item in server.sessions if item.get("session_name") == session_name),
        None,
    )
    if session is None and create:
        start_directory = current_app.config.get("TMUX_SHARED_SESSION_DIR")
        if not start_directory:
            start_directory = current_app.instance_path
        session = server.new_session(
            session_name=session_name,
            start_directory=start_directory,
            attach=False,
        )
        try:
            session.set_option("mouse", "off")
        except Exception:  # noqa: BLE001 - best effort
            current_app.logger.debug("Unable to set tmux session options for %s", session_name)
    return session


def ensure_project_window(project, *, window_name: Optional[str] = None):
    session = _ensure_shared_session()
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
        window = session.new_window(
            window_name=window_name,
            attach=False,
            start_directory=start_directory,
        )
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
) -> List[TmuxWindow]:
    session = _ensure_shared_session(create=False)
    if session is None:
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
            for window in session.windows
        ]

    matches: List[TmuxWindow] = []
    for window in session.windows:
        name = window.get("window_name", "").lower()
        if any(alias for alias in aliases if alias and alias in name):
            matches.append(_window_info(session, window))
    return matches


def get_or_create_window_for_project(project) -> TmuxWindow:
    session, window, _ = ensure_project_window(project)
    return _window_info(session, window)


def find_window_for_project(project) -> Optional[TmuxWindow]:
    session = _ensure_shared_session(create=False)
    if session is None:
        return None
    window = next(
        (item for item in session.windows if item.get("window_name") == _project_window_name(project)),
        None,
    )
    if window is None:
        return None
    return _window_info(session, window)


__all__ = [
    "TmuxWindow",
    "TmuxServiceError",
    "ensure_project_window",
    "get_or_create_window_for_project",
    "find_window_for_project",
    "list_windows_for_aliases",
]
