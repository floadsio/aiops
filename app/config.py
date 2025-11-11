import os
import shlex
from pathlib import Path

from .version import get_version

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _ensure_gemini_approval_mode(command: str, mode: str | None) -> str:
    if not mode:
        return command
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command
    for token in tokens:
        if token.startswith("--approval-mode"):
            return command
    return f"{command} --approval-mode {mode}"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'app.db').resolve()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REPO_STORAGE_PATH = os.getenv(
        "REPO_STORAGE_PATH", str((INSTANCE_DIR / "repos").resolve())
    )
    GEMINI_APPROVAL_MODE = os.getenv("GEMINI_APPROVAL_MODE", "auto_edit")
    CLI_EXTRA_PATHS = os.getenv("CLI_EXTRA_PATHS", "/opt/homebrew/bin:/usr/local/bin")
    _GEMINI_COMMAND = _ensure_gemini_approval_mode(
        os.getenv("GEMINI_COMMAND", "gemini"),
        GEMINI_APPROVAL_MODE,
    )
    ALLOWED_AI_TOOLS = {
        "codex": os.getenv("CODEX_COMMAND", "codex -a on-failure"),
        "aider": os.getenv("AIDER_COMMAND", "aider"),
        "gemini": _GEMINI_COMMAND,
        "claude": os.getenv("CLAUDE_COMMAND", "claude"),
    }
    DEFAULT_AI_TOOL = os.getenv("DEFAULT_AI_TOOL", "claude")
    DEFAULT_AI_SHELL = os.getenv("DEFAULT_AI_SHELL", "/bin/bash")
    DEFAULT_AI_ROWS = int(os.getenv("DEFAULT_AI_ROWS", "30"))
    DEFAULT_AI_COLS = int(os.getenv("DEFAULT_AI_COLS", "100"))
    USE_TMUX_FOR_AI_SESSIONS = os.getenv("USE_TMUX_FOR_AI_SESSIONS", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    TMUX_CONFIG_PATH = os.getenv(
        "TMUX_CONFIG_PATH",
        str((INSTANCE_DIR / "tmux.conf").resolve()),
    )
    DEFAULT_TMUX_CONFIG = "\n".join(
        [
            "set -g mouse off",
            "unbind -n WheelUpPane",
            "unbind -n WheelDownPane",
            "unbind -T root WheelUpPane",
            "unbind -T root WheelDownPane",
        ]
    )
    ANSIBLE_PLAYBOOK_DIR = os.getenv(
        "ANSIBLE_PLAYBOOK_DIR", str((Path("ansible") / "playbooks").resolve())
    )
    SEMAPHORE_BASE_URL = os.getenv("SEMAPHORE_BASE_URL")
    SEMAPHORE_API_TOKEN = os.getenv("SEMAPHORE_API_TOKEN")
    SEMAPHORE_DEFAULT_PROJECT_ID = (
        int(os.getenv("SEMAPHORE_DEFAULT_PROJECT_ID"))
        if os.getenv("SEMAPHORE_DEFAULT_PROJECT_ID")
        else None
    )
    SEMAPHORE_VERIFY_TLS = os.getenv("SEMAPHORE_VERIFY_TLS", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    SEMAPHORE_HTTP_TIMEOUT = float(os.getenv("SEMAPHORE_HTTP_TIMEOUT", "15"))
    SEMAPHORE_TASK_TIMEOUT = float(os.getenv("SEMAPHORE_TASK_TIMEOUT", "600"))
    SEMAPHORE_POLL_INTERVAL = float(os.getenv("SEMAPHORE_POLL_INTERVAL", "2"))
    UPDATE_RESTART_COMMAND = os.getenv("UPDATE_RESTART_COMMAND")
    GIT_AUTHOR_NAME = os.getenv("GIT_AUTHOR_NAME", "AI Ops Dashboard")
    GIT_AUTHOR_EMAIL = os.getenv("GIT_AUTHOR_EMAIL", "aiops@example.com")
    AIOPS_VERSION = get_version()
    LOG_FILE = os.getenv(
        "LOG_FILE",
        str((BASE_DIR / "logs" / "aiops.log").resolve()),
    )
    GEMINI_CONFIG_DIR = os.getenv("GEMINI_CONFIG_DIR", str((Path.home() / ".gemini")))
    CODEX_CONFIG_DIR = os.getenv("CODEX_CONFIG_DIR", str((Path.home() / ".codex")))
    CLAUDE_CONFIG_DIR = os.getenv("CLAUDE_CONFIG_DIR", str((Path.home() / ".claude")))
    CLAUDE_UPDATE_COMMAND = os.getenv(
        "CLAUDE_UPDATE_COMMAND", "sudo npm install -g @anthropic-ai/claude-code"
    )
    CLAUDE_BREW_PACKAGE = os.getenv("CLAUDE_BREW_PACKAGE", "claude-code")
