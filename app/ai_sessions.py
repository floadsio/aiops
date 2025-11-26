from __future__ import annotations

import fcntl
import os
import pty
import shlex
import shutil
import signal
import struct
import subprocess
import termios
import threading
import uuid
from base64 import b64encode
from pathlib import Path
from queue import Empty, Queue
from select import select
from typing import Optional

from flask import current_app

from .models import User
from .services.ai_session_service import save_session as save_session_to_db
from .services.codex_config_service import (
    CodexConfigError,
    ensure_codex_auth,
    sync_codex_credentials_for_linux_user,
)
from .services.gemini_config_service import (
    ensure_user_config,
    sync_credentials_to_cli_home,
)
from .services.git_service import build_project_git_env
from .services.cli_git_service import supports_cli_git
from .services.tmux_metadata import record_tmux_tool
from .services.tmux_service import ensure_project_window


def _backslash_quote(value: str) -> str:
    """Quote a string for shell using backslash escaping when possible.

    For simple strings (alphanumerics, spaces, and common punctuation), uses
    backslash escaping for better readability. Falls back to shlex.quote()
    for strings with special characters.

    Args:
        value: String to quote

    Returns:
        Quoted string suitable for shell use
    """
    import re

    # Check if string contains only safe characters that can be backslash-escaped
    # Allow letters, numbers, spaces, hyphens, underscores, dots, and @
    if re.match(r'^[a-zA-Z0-9 \-_.@]+$', value):
        # Use backslash escaping for spaces
        return value.replace(' ', r'\ ')
    else:
        # Fall back to shlex.quote for complex strings
        return shlex.quote(value)


def _build_cli_git_env_exports(project, user) -> list[str]:
    """Build environment variable exports for GitHub/GitLab CLI tools.

    Enables AI tools to use gh/glab commands directly in addition to aiops CLI.

    Args:
        project: Project model
        user: User model

    Returns:
        List of export commands for gh/glab authentication
    """
    exports = []

    # Check if project supports CLI git (has GitHub/GitLab integration with PAT)
    if not supports_cli_git(project):
        return exports

    # Get integration and provider
    integration = getattr(project, "integration", None)
    if not integration:
        return exports

    provider = getattr(integration, "provider", None)

    # Get token (check project override first, then tenant level)
    token = None
    project_integrations = getattr(project, "issue_integrations", [])
    for pi in project_integrations:
        if pi.integration_id == integration.id:
            override_token = getattr(pi, "override_api_token", None)
            if override_token:
                token = override_token
                break

    if not token:
        token = getattr(integration, "api_token", None) or getattr(integration, "access_token", None)

    if not token:
        return exports

    # Get base URL (check project override first, then tenant level)
    base_url = None
    for pi in project_integrations:
        if pi.integration_id == integration.id:
            override_url = getattr(pi, "override_base_url", None)
            if override_url:
                base_url = override_url.rstrip("/")
                break

    if not base_url:
        base_url = getattr(integration, "base_url", None)
        if base_url:
            base_url = base_url.rstrip("/")

    # Export environment variables based on provider
    if provider == "github":
        exports.append(f"export GH_TOKEN={shlex.quote(token)}")
        # Only set GH_HOST for GitHub Enterprise (not github.com)
        if base_url and "github.com" not in base_url:
            exports.append(f"export GH_HOST={shlex.quote(base_url)}")
    elif provider == "gitlab":
        exports.append(f"export GITLAB_TOKEN={shlex.quote(token)}")
        # Only set GITLAB_HOST for private instances (not gitlab.com)
        if base_url and "gitlab.com" not in base_url:
            exports.append(f"export GITLAB_HOST={shlex.quote(base_url)}")

    return exports


class AISession:
    def __init__(
        self,
        session_id: str,
        project_id: int,
        user_id: int,
        tool: str | None,
        command: str,
        pid: int,
        fd: int,
        tmux_target: str | None = None,
        issue_id: int | None = None,
    ):
        import time
        self.id = session_id
        self.project_id = project_id
        self.user_id = user_id
        self.tool = tool
        self.command = command
        self.pid = pid
        self.fd = fd
        self.tmux_target = tmux_target
        self.issue_id = issue_id
        self.queue: Queue[bytes | None] = Queue()
        self.stop_event = threading.Event()
        self.is_persistent = False
        self.created_at = time.time()

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


class PersistentAISession:
    """Persistent AI session that survives backend restarts.

    Uses tmux pipe-pane for output capture instead of PTY fork,
    allowing sessions to persist independently of the backend process.
    """
    def __init__(
        self,
        session_id: str,
        project_id: int,
        user_id: int,
        tool: str | None,
        command: str,
        tmux_target: str,
        pipe_file: str,
        issue_id: int | None = None,
    ):
        import time
        self.id = session_id
        self.project_id = project_id
        self.user_id = user_id
        self.tool = tool
        self.command = command
        self.tmux_target = tmux_target
        self.pipe_file = pipe_file
        self.issue_id = issue_id
        self.queue: Queue[bytes | None] = Queue()
        self.stop_event = threading.Event()
        self.is_persistent = True
        # Track file position for reading output
        self._file_position = 0
        self.created_at = time.time()

    def close(self) -> None:
        """Stop streaming output but leave tmux session running."""
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        # Note: We don't kill the tmux session - it persists independently


_sessions: dict[str, AISession] = {}
_sessions_lock = threading.Lock()


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
    except (OSError, ValueError):
        pass


def _resolve_command(tool: str | None, command: str | None, permission_mode: str | None = None) -> str:
    tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    fallback_shell = current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    default_tool = current_app.config.get("DEFAULT_AI_TOOL", "claude")

    if command:
        return command

    if tool:
        command_str = tool_commands.get(tool)
        if not command_str:
            raise ValueError("Unsupported AI tool")
        # Override permission mode for Claude if specified
        if tool == "claude" and permission_mode:
            from .config import _ensure_claude_permission_mode
            command_str = _ensure_claude_permission_mode(command_str, permission_mode)
        return command_str

    command_str = tool_commands.get(default_tool)
    if command_str:
        # Override permission mode for Claude if default tool is Claude and permission_mode specified
        if default_tool == "claude" and permission_mode:
            from .config import _ensure_claude_permission_mode
            command_str = _ensure_claude_permission_mode(command_str, permission_mode)
        return command_str

    return fallback_shell


def _first_command_token(command: str | None) -> str | None:
    if not command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    return tokens[0] if tokens else None


def _uses_gemini(command_str: str, tool: str | None) -> bool:
    tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    configured = tool_commands.get("gemini")
    if tool == "gemini":
        return True
    configured_token = _first_command_token(configured)
    command_token = _first_command_token(command_str)
    return bool(
        configured_token and command_token and configured_token == command_token
    )


def _uses_codex(command_str: str, tool: str | None) -> bool:
    tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    configured = tool_commands.get("codex")
    if tool == "codex":
        return True
    configured_token = _first_command_token(configured)
    command_token = _first_command_token(command_str)
    return bool(
        configured_token and command_token and configured_token == command_token
    )


def _uses_claude(command_str: str, tool: str | None) -> bool:
    tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    configured = tool_commands.get("claude")
    if tool == "claude":
        return True
    configured_token = _first_command_token(configured)
    command_token = _first_command_token(command_str)
    return bool(
        configured_token and command_token and configured_token == command_token
    )


def _is_interactive_tool(command_str: str, tool: str | None) -> bool:
    """Check if the command is for an interactive AI tool that needs stdin connected to TTY.

    Interactive tools like Claude Code, Codex, and Gemini CLI use terminal UI libraries
    (Ink, etc.) that require raw mode access to stdin. These cannot work with heredoc
    input redirection.

    Plain bash/shell commands also need to run interactively to keep the shell alive.
    """
    return (
        _uses_claude(command_str, tool)
        or _uses_codex(command_str, tool)
        or _uses_gemini(command_str, tool)
        or command_str.strip() in ("/bin/bash", "/bin/zsh", "/bin/sh", "bash", "zsh", "sh")
    )


def _resolve_tmux_window(
    project,
    user,
    tmux_target: Optional[str] = None,
    *,
    session_name: Optional[str] = None,
    linux_username: Optional[str] = None,
):
    window_name = None
    if tmux_target:
        if ":" in tmux_target:
            _, _, suffix = tmux_target.partition(":")
            window_name = suffix or tmux_target
        else:
            window_name = tmux_target

    try:
        session, window, created = ensure_project_window(
            project,
            window_name=window_name,
            session_name=session_name,
            linux_username=linux_username,
            user=user,
        )
    except ValueError as exc:
        current_app.logger.warning(
            "Unable to open tmux window %s for project %s: %s. Falling back to default window.",
            window_name,
            getattr(project, "id", "unknown"),
            exc,
        )
        session, window, created = ensure_project_window(
            project,
            session_name=session_name,
            linux_username=linux_username,
            user=user,
        )
    try:
        window.select_window()
    except Exception:  # noqa: BLE001 - best effort
        current_app.logger.debug(
            "Unable to select tmux window %s:%s",
            session.get("session_name"),
            window.get("window_name"),
        )
    return session, window, created


def _register_session(session: AISession) -> AISession:
    with _sessions_lock:
        _sessions[session.id] = session
    return session


def get_session(session_id: str) -> Optional[AISession]:
    with _sessions_lock:
        return _sessions.get(session_id)


def session_exists(tmux_target: str) -> bool:
    """Check if a tmux session/window exists.

    Args:
        tmux_target: The tmux target (session:window format or session name)

    Returns:
        True if the tmux session exists, False otherwise
    """
    import subprocess

    try:
        # Use tmux has-session to check if target exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", tmux_target],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):  # noqa: BLE001
        return False


def find_session_for_issue(
    issue_id: int,
    user_id: int,
    project_id: int,
    *,
    expected_tool: str | None = None,
    expected_command: str | None = None,
) -> Optional[AISession]:
    """Find an active AI session working on a specific issue for a user.

    Args:
        issue_id: The issue ID to search for
        user_id: The user ID who owns the session
        project_id: The project ID (for additional filtering)
        expected_tool: If specified, only return sessions with this tool
        expected_command: If specified, only return sessions with this command

    Returns:
        AISession if found and still active, None otherwise.
        If expected_tool is None, returns the most recently created matching session.
    """
    with _sessions_lock:
        matching_sessions = []

        for session in _sessions.values():
            if (
                session.issue_id == issue_id
                and session.user_id == user_id
                and session.project_id == project_id
                and not session.stop_event.is_set()
            ):
                # Verify the tmux window actually exists before returning the session
                if session.tmux_target and not session_exists(session.tmux_target):
                    # Tmux window is gone, mark session as stopped
                    session.stop_event.set()
                    continue

                # If expected_tool is specified, filter by tool
                if expected_tool is not None:
                    if getattr(session, "tool", None) != expected_tool:
                        continue

                # If expected_command is specified, filter by command
                if expected_command is not None and session.command != expected_command:
                    continue

                matching_sessions.append(session)

        # If no expected_tool, return the most recently created session
        # Otherwise return any matching session (they all have the same tool)
        if matching_sessions:
            # Sort by creation time (most recent first) and return the newest
            matching_sessions.sort(key=lambda s: getattr(s, 'created_at', 0), reverse=True)
            return matching_sessions[0]

    return None


def list_active_sessions(user_id: int | None = None, project_id: int | None = None) -> list[AISession]:
    """List all active AI sessions, optionally filtered by user or project.

    Args:
        user_id: Optional user ID to filter by
        project_id: Optional project ID to filter by

    Returns:
        List of active AISession objects
    """
    with _sessions_lock:
        sessions = []
        for session in _sessions.values():
            # Skip stopped sessions
            if session.stop_event.is_set():
                continue

            # Apply filters
            if user_id is not None and session.user_id != user_id:
                continue
            if project_id is not None and session.project_id != project_id:
                continue

            sessions.append(session)

        return sessions


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


def _pipe_reader_loop(session: PersistentAISession) -> None:
    """Read output from tmux pipe file and put into queue."""
    try:
        # Wait for pipe file to be created
        max_wait = 5
        waited = 0
        while not os.path.exists(session.pipe_file) and waited < max_wait:
            if session.stop_event.is_set():
                return
            threading.Event().wait(0.1)
            waited += 0.1

        if not os.path.exists(session.pipe_file):
            current_app.logger.warning(
                "Pipe file %s not created after %ds", session.pipe_file, max_wait
            )
            return

        with open(session.pipe_file, "rb") as f:
            # Seek to tracked position (for reconnections)
            if session._file_position > 0:
                f.seek(session._file_position)

            while not session.stop_event.is_set():
                # Read new data
                data = f.read(1024)
                if data:
                    session._file_position = f.tell()
                    session.queue.put(data)
                else:
                    # No new data, wait a bit
                    threading.Event().wait(0.1)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(
            "Error reading pipe file for session %s: %s", session.id, exc
        )
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
    tmux_session_name: str | None = None,
    issue_id: int | None = None,
    permission_mode: str | None = None,
) -> AISession:
    current_app.logger.warning(f"DEBUG: create_session called with tool={tool}, command={command}")
    command_str = _resolve_command(tool, command, permission_mode=permission_mode)
    current_app.logger.warning(f"DEBUG: Resolved command: {command_str}")
    uses_gemini = _uses_gemini(command_str, tool)
    if uses_gemini:
        ensure_user_config(user_id)
        sync_credentials_to_cli_home(user_id)
    # Prepare Git author information from user
    # Also grab linux_username before fork since DB session won't be available after fork
    user = User.query.get(user_id)
    linux_username_for_session = None
    git_author_exports: list[str] = []
    aiops_env_exports: list[str] = []
    cli_git_env_exports: list[str] = []
    if user:
        from .services.linux_users import resolve_linux_username
        linux_username_for_session = resolve_linux_username(user)

    # Now that we know the linux_username, we can properly configure codex credentials
    uses_codex = _uses_codex(command_str, tool)
    codex_env_exports: list[str] = []
    if uses_codex:
        try:
            # For per-user sessions, sync credentials to the target user's home
            # For system sessions (syseng), use the standard path
            if linux_username_for_session and linux_username_for_session != "syseng":
                cli_auth_path = sync_codex_credentials_for_linux_user(
                    user_id, linux_username_for_session
                )
            else:
                cli_auth_path = ensure_codex_auth(user_id)
        except CodexConfigError as exc:
            current_app.logger.warning(
                "Codex credentials unavailable for user %s: %s", user_id, exc
            )
        else:
            codex_env_exports.append(
                f"export CODEX_CONFIG_DIR={shlex.quote(str(cli_auth_path.parent))}"
            )
            codex_env_exports.append(
                f"export CODEX_AUTH_FILE={shlex.quote(str(cli_auth_path))}"
            )
    # Claude uses web auth, no token injection needed
    claude_env_exports: list[str] = []

    default_rows = current_app.config.get("DEFAULT_AI_ROWS", 30)
    default_cols = current_app.config.get("DEFAULT_AI_COLS", 100)
    rows = rows or default_rows
    cols = cols or default_cols

    # Continue setting up user environment
    if user:
        git_author_exports.append(f"export GIT_AUTHOR_NAME={_backslash_quote(user.name)}")
        git_author_exports.append(f"export GIT_AUTHOR_EMAIL={_backslash_quote(user.email)}")
        git_author_exports.append(f"export GIT_COMMITTER_NAME={_backslash_quote(user.name)}")
        git_author_exports.append(
            f"export GIT_COMMITTER_EMAIL={_backslash_quote(user.email)}"
        )
        # AIOPS CLI credentials injection
        if user.aiops_cli_url:
            aiops_env_exports.append(
                f"export AIOPS_URL={shlex.quote(user.aiops_cli_url)}"
            )
        if user.aiops_cli_api_key:
            aiops_env_exports.append(
                f"export AIOPS_API_KEY={shlex.quote(user.aiops_cli_api_key)}"
            )

    # GitHub/GitLab CLI tool credentials (gh/glab) for both backend and AI use
    cli_git_env_exports = _build_cli_git_env_exports(project, user)

    tmux_path = shutil.which("tmux")
    if not tmux_path:
        raise RuntimeError(
            "tmux binary not found. Install tmux or disable tmux integration."
        )

    session, window, created = _resolve_tmux_window(
        project,
        user,
        tmux_target,
        session_name=tmux_session_name,
        linux_username=linux_username_for_session,
    )
    session_name = session.get("session_name")
    window_name = window.get("window_name")
    pane = window.attached_pane or (window.panes[0] if window.panes else None)
    if pane is None:
        raise RuntimeError("Unable to access tmux pane for project window.")

    # For per-user sessions, don't inject project SSH keys - let users use their own
    # For system sessions (syseng), use project SSH keys
    use_project_ssh_keys = linux_username_for_session is None

    git_env = build_project_git_env(project)
    for key, value in git_env.items():
        if value:
            os.environ[key] = value

    # Only pass SSH command to user sessions if we want to use project keys
    ssh_command = git_env.get("GIT_SSH_COMMAND") if use_project_ssh_keys else None

    # Determine start directory (needed for both child and parent processes)
    start_dir = current_app.instance_path
    if user is not None:
        from .services.workspace_service import get_workspace_path

        workspace_path = get_workspace_path(project, user)
        if workspace_path is not None:
            start_dir = str(workspace_path)

    # Build tmux attach command (runs as syseng, the Flask app user)
    exec_args = [tmux_path, "attach-session", "-t", f"{session_name}:{window_name}"]

    session_id = uuid.uuid4().hex

    pid, fd = pty.fork()
    if pid == 0:  # child process
        try:
            os.chdir(start_dir)
        except FileNotFoundError:
            os.makedirs(start_dir, exist_ok=True)
            os.chdir(start_dir)
        os.environ.setdefault("TERM", "xterm-256color")
        os.environ.pop("TMUX", None)
        if rows and cols:
            _set_winsize(1, rows, cols)

        # tmux attach runs as the Flask app user (syseng)
        # Commands inside the tmux pane will use sudo to run as the target Linux user
        try:
            os.execvp(exec_args[0], exec_args)
        except FileNotFoundError:
            os.write(1, f"Command not found: {exec_args[0]}\r\n".encode())
            os._exit(1)

    session_record = AISession(
        session_id,
        project.id,
        user_id,
        tool,
        command_str,
        pid,
        fd,
        f"{session_name}:{window_name}",
        issue_id=issue_id,
    )
    if rows and cols:
        _set_winsize(fd, rows, cols)
    _register_session(session_record)

    # Always bootstrap (use sudo) for per-user sessions, even when reusing windows
    # This ensures commands run with the correct user UID
    should_bootstrap = created or tmux_target is None or (
        linux_username_for_session and linux_username_for_session != "syseng"
    )
    if should_bootstrap:
        # When running as a different Linux user, start an interactive login shell
        # so user configs (.bashrc, .profile) are loaded
        if linux_username_for_session and linux_username_for_session != "syseng":
            use_login_shell = current_app.config.get("USE_LOGIN_SHELL", True)
            shell_cmd = "bash -l" if use_login_shell else "bash"

            # Check if this is an interactive tool that needs stdin connected to TTY
            is_interactive = _is_interactive_tool(command_str, tool)

            if is_interactive:
                # For interactive tools (claude, codex, gemini), use bash -c to preserve stdin
                # For plain shells (bash, zsh), exec the shell directly after setup
                is_plain_shell = command_str.strip() in ("/bin/bash", "/bin/zsh", "/bin/sh", "bash", "zsh", "sh")

                setup_commands = []

                # Change to workspace directory
                setup_commands.append(f"cd {shlex.quote(start_dir)} 2>/dev/null || true")

                # Export environment variables
                if ssh_command:
                    setup_commands.append(f"export GIT_SSH_COMMAND={shlex.quote(ssh_command)}")
                for export_cmd in git_author_exports:
                    setup_commands.append(export_cmd)
                for export_cmd in codex_env_exports:
                    setup_commands.append(export_cmd)
                for export_cmd in claude_env_exports:
                    setup_commands.append(export_cmd)
                for export_cmd in aiops_env_exports:
                    setup_commands.append(export_cmd)
                for export_cmd in cli_git_env_exports:
                    setup_commands.append(export_cmd)

                # Clear screen
                setup_commands.append("clear")

                # For plain shells, exec the shell to replace the process
                # For AI tools, just run the command
                if is_plain_shell:
                    setup_commands.append(f"exec {command_str}")
                else:
                    setup_commands.append(command_str)

                # Join commands with && and quote for bash -c
                command_chain = " && ".join(setup_commands)
                final_command = f"sudo -u {linux_username_for_session} {shell_cmd} -c {shlex.quote(command_chain)}"

                current_app.logger.info(
                    "Starting interactive tool as user %s in %s (preserving stdin)",
                    linux_username_for_session,
                    start_dir,
                )
            else:
                # For non-interactive commands, use heredoc (original behavior)
                script_lines = []

                # Change to workspace directory
                script_lines.append(f"cd {shlex.quote(start_dir)} 2>/dev/null || true")

                # Export environment variables
                if ssh_command:
                    script_lines.append(f"export GIT_SSH_COMMAND={shlex.quote(ssh_command)}")
                for export_cmd in git_author_exports:
                    script_lines.append(export_cmd)
                for export_cmd in codex_env_exports:
                    script_lines.append(export_cmd)
                for export_cmd in claude_env_exports:
                    script_lines.append(export_cmd)
                for export_cmd in cli_git_env_exports:
                    script_lines.append(export_cmd)

                # Clear and run the command
                script_lines.append("clear")
                script_lines.append(command_str)

                # Create the sudo command with a heredoc
                script_body = "\n".join(script_lines)
                final_command = (
                    f"sudo -u {linux_username_for_session} {shell_cmd} <<'AIOPS_EOF'\n"
                    f"{script_body}\n"
                    f"AIOPS_EOF"
                )
                current_app.logger.info(
                    "Starting login shell as user %s in %s",
                    linux_username_for_session,
                    start_dir,
                )
        else:
            # Running as syseng - use the original approach
            if ssh_command:
                export_command = f"export GIT_SSH_COMMAND={shlex.quote(ssh_command)}"
                try:
                    pane.send_keys(export_command, enter=True)
                except Exception:  # noqa: BLE001
                    current_app.logger.debug(
                        "Unable to set GIT_SSH_COMMAND for %s", window_name
                    )
            for export_command in git_author_exports:
                try:
                    pane.send_keys(export_command, enter=True)
                except Exception:  # noqa: BLE001
                    current_app.logger.debug(
                        "Unable to set Git author environment for %s", window_name
                    )
            for export_command in codex_env_exports:
                try:
                    pane.send_keys(export_command, enter=True)
                except Exception:  # noqa: BLE001
                    current_app.logger.debug(
                        "Unable to set Codex environment for %s", window_name
                    )
            for export_command in claude_env_exports:
                try:
                    pane.send_keys(export_command, enter=True)
                except Exception:  # noqa: BLE001
                    current_app.logger.debug(
                        "Unable to set Claude environment for %s", window_name
                    )
            try:
                pane.send_keys("clear", enter=True)
            except Exception:  # noqa: BLE001
                current_app.logger.debug("Unable to clear tmux pane for %s", window_name)
            final_command = command_str

        try:
            pane.send_keys(final_command, enter=True)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(
                "Failed to start command in tmux window %s: %s", window_name, exc
            )
    else:
        try:
            pane.send_keys("clear", enter=True)
        except Exception:  # noqa: BLE001
            current_app.logger.debug("Unable to clear tmux pane for %s", window_name)

    if tool:
        record_tmux_tool(session_record.tmux_target, tool)
    threading.Thread(target=_reader_loop, args=(session_record,), daemon=True).start()

    # Save session to database for persistence and listing
    save_session_to_db(
        project_id=project.id,
        user_id=user_id,
        tool=tool or "shell",
        session_id=session_id,
        command=command_str,
        description=None,
        tmux_target=session_record.tmux_target,
        issue_id=issue_id,
    )

    return session_record


def create_persistent_session(
    project,
    user_id: int,
    tool: str | None = None,
    command: str | None = None,
    rows: int | None = None,
    cols: int | None = None,
    tmux_target: str | None = None,
    tmux_session_name: str | None = None,
    issue_id: int | None = None,
    permission_mode: str | None = None,
) -> PersistentAISession:
    """Create a persistent AI session that survives backend restarts.

    Uses tmux pipe-pane for output capture instead of PTY fork.
    """
    command_str = _resolve_command(tool, command, permission_mode=permission_mode)
    uses_gemini = _uses_gemini(command_str, tool)
    if uses_gemini:
        ensure_user_config(user_id)
        sync_credentials_to_cli_home(user_id)

    # Get user info
    user = User.query.get(user_id)
    linux_username_for_session = None
    git_author_exports: list[str] = []
    aiops_env_exports: list[str] = []
    if user:
        from .services.linux_users import resolve_linux_username
        linux_username_for_session = resolve_linux_username(user)

    # Configure codex credentials
    uses_codex = _uses_codex(command_str, tool)
    codex_env_exports: list[str] = []
    if uses_codex:
        try:
            if linux_username_for_session and linux_username_for_session != "syseng":
                cli_auth_path = sync_codex_credentials_for_linux_user(
                    user_id, linux_username_for_session
                )
            else:
                cli_auth_path = ensure_codex_auth(user_id)
        except CodexConfigError as exc:
            current_app.logger.warning(
                "Codex credentials unavailable for user %s: %s", user_id, exc
            )
        else:
            codex_env_exports.append(
                f"export CODEX_CONFIG_DIR={shlex.quote(str(cli_auth_path.parent))}"
            )
            codex_env_exports.append(
                f"export CODEX_AUTH_FILE={shlex.quote(str(cli_auth_path))}"
            )

    claude_env_exports: list[str] = []

    # Set up user environment
    if user:
        git_author_exports.append(f"export GIT_AUTHOR_NAME={_backslash_quote(user.name)}")
        git_author_exports.append(f"export GIT_AUTHOR_EMAIL={_backslash_quote(user.email)}")
        git_author_exports.append(f"export GIT_COMMITTER_NAME={_backslash_quote(user.name)}")
        git_author_exports.append(
            f"export GIT_COMMITTER_EMAIL={_backslash_quote(user.email)}"
        )
        if user.aiops_cli_url:
            aiops_env_exports.append(
                f"export AIOPS_URL={shlex.quote(user.aiops_cli_url)}"
            )
        if user.aiops_cli_api_key:
            aiops_env_exports.append(
                f"export AIOPS_API_KEY={shlex.quote(user.aiops_cli_api_key)}"
            )

    # Ensure tmux window exists
    session, window, created = _resolve_tmux_window(
        project,
        user,
        tmux_target,
        session_name=tmux_session_name,
        linux_username=linux_username_for_session,
    )
    session_name = session.get("session_name")
    window_name = window.get("window_name")
    pane = window.attached_pane or (window.panes[0] if window.panes else None)
    if pane is None:
        raise RuntimeError("Unable to access tmux pane for project window.")

    use_project_ssh_keys = linux_username_for_session is None
    git_env = build_project_git_env(project)
    ssh_command = git_env.get("GIT_SSH_COMMAND") if use_project_ssh_keys else None

    # Determine start directory
    start_dir = current_app.instance_path
    if user is not None:
        from .services.workspace_service import get_workspace_path
        workspace_path = get_workspace_path(project, user)
        if workspace_path is not None:
            start_dir = str(workspace_path)

    session_id = uuid.uuid4().hex
    pipe_dir = Path(current_app.instance_path) / "session_pipes"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    pipe_file = str(pipe_dir / f"{session_id}.log")

    # Set up tmux pipe-pane for output capture
    tmux_target_full = f"{session_name}:{window_name}"

    # Enable remain-on-exit so pane stays alive even if shell exits
    try:
        subprocess.run(
            ["tmux", "set-option", "-t", tmux_target_full, "remain-on-exit", "on"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        current_app.logger.info("Enabled remain-on-exit for %s", tmux_target_full)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        current_app.logger.warning("Failed to enable remain-on-exit: %s", exc)

    try:
        subprocess.run(
            ["tmux", "pipe-pane", "-t", tmux_target_full, "-o", f"cat >> {shlex.quote(pipe_file)}"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        current_app.logger.info("Set up pipe-pane for %s -> %s", tmux_target_full, pipe_file)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        current_app.logger.warning("Failed to set up pipe-pane: %s", exc)

    # Build and send the command
    should_bootstrap = created or tmux_target is None or (
        linux_username_for_session and linux_username_for_session != "syseng"
    )

    if should_bootstrap:
        if linux_username_for_session and linux_username_for_session != "syseng":
            use_login_shell = current_app.config.get("USE_LOGIN_SHELL", True)
            shell_cmd = "bash -l" if use_login_shell else "bash"
            is_plain_shell = command_str.strip() in ("/bin/bash", "/bin/zsh", "/bin/sh", "bash", "zsh", "sh")

            setup_commands = []
            setup_commands.append(f"cd {shlex.quote(start_dir)} 2>/dev/null || true")
            if ssh_command:
                setup_commands.append(f"export GIT_SSH_COMMAND={shlex.quote(ssh_command)}")
            for export_cmd in git_author_exports + codex_env_exports + claude_env_exports + aiops_env_exports:
                setup_commands.append(export_cmd)
            setup_commands.append("clear")

            if is_plain_shell:
                setup_commands.append(f"exec {command_str}")
            else:
                setup_commands.append(command_str)

            command_chain = " && ".join(setup_commands)
            final_command = f"sudo -u {linux_username_for_session} {shell_cmd} -c {shlex.quote(command_chain)}"
        else:
            # Running as syseng
            if ssh_command:
                try:
                    pane.send_keys(f"export GIT_SSH_COMMAND={shlex.quote(ssh_command)}", enter=True)
                except Exception:  # noqa: BLE001
                    pass
            for export_cmd in git_author_exports + codex_env_exports + claude_env_exports + aiops_env_exports:
                try:
                    pane.send_keys(export_cmd, enter=True)
                except Exception:  # noqa: BLE001
                    pass
            try:
                pane.send_keys("clear", enter=True)
            except Exception:  # noqa: BLE001
                pass
            final_command = command_str

        try:
            pane.send_keys(final_command, enter=True)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(
                "Failed to start command in tmux window %s: %s", window_name, exc
            )

    # Create persistent session object
    session_record = PersistentAISession(
        session_id,
        project.id,
        user_id,
        tool,
        command_str,
        tmux_target_full,
        pipe_file,
        issue_id=issue_id,
    )
    _register_session(session_record)

    if tool:
        record_tmux_tool(session_record.tmux_target, tool)

    # Start pipe reader thread
    threading.Thread(target=_pipe_reader_loop, args=(session_record,), daemon=True).start()

    # Save to database
    save_session_to_db(
        project_id=project.id,
        user_id=user_id,
        tool=tool or "shell",
        session_id=session_id,
        command=command_str,
        description=None,
        tmux_target=session_record.tmux_target,
        issue_id=issue_id,
    )

    current_app.logger.info(
        "Created persistent session %s for user %s in project %s",
        session_id[:12],
        user_id,
        project.id,
    )

    return session_record


def write_to_session(session: AISession | PersistentAISession, data: str) -> None:
    if session.stop_event.is_set():
        return

    if isinstance(session, PersistentAISession):
        # Use tmux send-keys for persistent sessions
        try:
            # Send keys without adding newline (user controls when to press enter)
            subprocess.run(
                ["tmux", "send-keys", "-t", session.tmux_target, "-l", data],
                check=False,
                capture_output=True,
                timeout=1,
            )
        except (subprocess.TimeoutExpired, Exception) as exc:  # noqa: BLE001
            current_app.logger.warning("Failed to send keys to session %s: %s", session.id, exc)
    else:
        # Use PTY for legacy sessions
        os.write(session.fd, data.encode())


def close_session(session: AISession | PersistentAISession) -> None:
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
