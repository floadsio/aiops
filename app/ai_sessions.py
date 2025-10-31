from __future__ import annotations

import fcntl
import os
import pty
import shutil
import signal
import struct
import threading
import termios
import uuid
from base64 import b64encode
from queue import Empty, Queue
from select import select
from typing import Optional

from flask import current_app
from .services.tmux_service import ensure_project_window


class AISession:
    def __init__(
        self,
        session_id: str,
        project_id: int,
        user_id: int,
        command: str,
        pid: int,
        fd: int,
        tmux_target: str | None = None,
    ):
        self.id = session_id
        self.project_id = project_id
        self.user_id = user_id
        self.command = command
        self.pid = pid
        self.fd = fd
        self.tmux_target = tmux_target
        self.queue: Queue[bytes | None] = Queue()
        self.stop_event = threading.Event()

    def close(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


_sessions: dict[str, AISession] = {}
_sessions_lock = threading.Lock()


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
    except (OSError, ValueError):
        pass


def _resolve_command(tool: str | None, command: str | None) -> str:
    tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    fallback_shell = current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    default_tool = current_app.config.get("DEFAULT_AI_TOOL", "codex")

    if command:
        return command

    if tool:
        command_str = tool_commands.get(tool)
        if not command_str:
            raise ValueError("Unsupported AI tool")
        return command_str

    command_str = tool_commands.get(default_tool)
    if command_str:
        return command_str

    return fallback_shell


def _resolve_tmux_window(project, tmux_target: Optional[str] = None):
    window_name = None
    if tmux_target:
        if ":" in tmux_target:
            _, _, suffix = tmux_target.partition(":")
            window_name = suffix or tmux_target
        else:
            window_name = tmux_target

    try:
        session, window, created = ensure_project_window(project, window_name=window_name)
    except ValueError as exc:
        current_app.logger.warning(
            "Unable to open tmux window %s for project %s: %s. Falling back to default window.",
            window_name,
            getattr(project, "id", "unknown"),
            exc,
        )
        session, window, created = ensure_project_window(project)
    try:
        window.select_window()
    except Exception:  # noqa: BLE001 - best effort
        current_app.logger.debug(
            "Unable to select tmux window %s:%s", session.get("session_name"), window.get("window_name")
        )
    return session, window, created


def _register_session(session: AISession) -> AISession:
    with _sessions_lock:
        _sessions[session.id] = session
    return session


def get_session(session_id: str) -> Optional[AISession]:
    with _sessions_lock:
        return _sessions.get(session_id)


def remove_session(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)


def _reader_loop(session: AISession) -> None:
    try:
        while not session.stop_event.is_set():
            r, _, _ = select([session.fd], [], [], 0.1)
            if session.fd in r:
                try:
                    data = os.read(session.fd, 1024)
                except OSError:
                    break
                if not data:
                    break
                session.queue.put(data)
    finally:
        session.queue.put(None)
        session.stop_event.set()
        remove_session(session.id)


def create_session(
    project,
    user_id: int,
    tool: str | None = None,
    command: str | None = None,
    rows: int | None = None,
    cols: int | None = None,
    tmux_target: str | None = None,
) -> AISession:
    command_str = _resolve_command(tool, command)

    default_rows = current_app.config.get("DEFAULT_AI_ROWS", 30)
    default_cols = current_app.config.get("DEFAULT_AI_COLS", 100)
    rows = rows or default_rows
    cols = cols or default_cols

    tmux_path = shutil.which("tmux")
    if not tmux_path:
        raise RuntimeError("tmux binary not found. Install tmux or disable tmux integration.")

    session, window, created = _resolve_tmux_window(project, tmux_target)
    session_name = session.get("session_name")
    window_name = window.get("window_name")
    pane = window.attached_pane or (window.panes[0] if window.panes else None)
    if pane is None:
        raise RuntimeError("Unable to access tmux pane for project window.")

    exec_args = [tmux_path, "attach-session", "-t", f"{session_name}:{window_name}"]

    session_id = uuid.uuid4().hex

    pid, fd = pty.fork()
    if pid == 0:  # child process
        start_dir = getattr(project, "local_path", None) or current_app.instance_path
        try:
            os.chdir(start_dir)
        except FileNotFoundError:
            os.makedirs(start_dir, exist_ok=True)
            os.chdir(start_dir)
        os.environ.setdefault("TERM", "xterm-256color")
        os.environ.pop("TMUX", None)
        if rows and cols:
            _set_winsize(1, rows, cols)
        try:
            os.execvp(exec_args[0], exec_args)
        except FileNotFoundError:
            os.write(1, f"Command not found: {exec_args[0]}\r\n".encode())
            os._exit(1)

    session_record = AISession(
        session_id,
        project.id,
        user_id,
        command_str,
        pid,
        fd,
        f"{session_name}:{window_name}"
    )
    if rows and cols:
        _set_winsize(fd, rows, cols)
    _register_session(session_record)

    should_bootstrap = created or tmux_target is None
    if should_bootstrap:
        try:
            pane.send_keys("clear", enter=True)
        except Exception:  # noqa: BLE001
            current_app.logger.debug("Unable to clear tmux pane for %s", window_name)
        try:
            pane.send_keys(command_str, enter=True)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning("Failed to start command in tmux window %s: %s", window_name, exc)

    threading.Thread(target=_reader_loop, args=(session_record,), daemon=True).start()
    return session_record


def write_to_session(session: AISession, data: str) -> None:
    if session.stop_event.is_set():
        return
    os.write(session.fd, data.encode())


def close_session(session: AISession) -> None:
    session.close()
    remove_session(session.id)


def resize_session(session: AISession, rows: int, cols: int) -> None:
    if session.stop_event.is_set():
        return
    if rows <= 0 or cols <= 0:
        return
    _set_winsize(session.fd, rows, cols)


def stream_session(session: AISession):
    keepalive_interval = 0.5
    while not session.stop_event.is_set():
        try:
            chunk = session.queue.get(timeout=keepalive_interval)
        except Empty:
            yield "event: keepalive\ndata: ping\n\n"
            continue

        if chunk is None:
            break

        encoded = b64encode(chunk).decode()
        yield f"event: chunk\ndata: {encoded}\n\n"
    yield "event: close\ndata: session-closed\n\n"
