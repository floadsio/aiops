import os
import shlex
from pathlib import Path

from .version import get_version

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_PATH = str(INSTANCE_DIR.resolve())


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


def _get_int_env_var(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _ensure_codex_flags(
    command: str,
    *,
    sandbox_mode: str | None,
    approval_mode: str | None,
) -> str:
    if not command:
        return command
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command

    def ensure_flag(flag: str, value: str | None) -> None:
        if not value:
            return
        for idx, token in enumerate(tokens):
            if token == flag and idx + 1 < len(tokens):
                tokens[idx + 1] = value
                return
            if token.startswith(f"{flag}="):
                tokens[idx] = flag
                if idx + 1 < len(tokens):
                    tokens[idx + 1] = value
                else:
                    tokens.insert(idx + 1, value)
                return
        tokens.extend([flag, value])

    ensure_flag("--sandbox", sandbox_mode)
    ensure_flag("--ask-for-approval", approval_mode)
    return shlex.join(tokens)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    INSTANCE_PATH = INSTANCE_PATH
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'app.db').resolve()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REPO_STORAGE_PATH = os.getenv(
        "REPO_STORAGE_PATH", str((INSTANCE_DIR / "repos").resolve())
    )
    AIOPS_ROOT = os.getenv("AIOPS_ROOT", str(BASE_DIR.resolve()))
    GEMINI_APPROVAL_MODE = os.getenv("GEMINI_APPROVAL_MODE", "auto_edit")
    CLI_EXTRA_PATHS = os.getenv("CLI_EXTRA_PATHS", "/opt/homebrew/bin:/usr/local/bin")
    CODEX_SANDBOX_MODE = os.getenv("CODEX_SANDBOX_MODE", "danger-full-access")
    CODEX_APPROVAL_MODE = os.getenv("CODEX_APPROVAL_MODE", "never")
    _GEMINI_COMMAND = _ensure_gemini_approval_mode(
        os.getenv("GEMINI_COMMAND", "gemini"),
        GEMINI_APPROVAL_MODE,
    )
    _CODEX_COMMAND = _ensure_codex_flags(
        os.getenv("CODEX_COMMAND", "codex"),
        sandbox_mode=CODEX_SANDBOX_MODE,
        approval_mode=CODEX_APPROVAL_MODE,
    )
    ALLOWED_AI_TOOLS = {
        "codex": _CODEX_COMMAND,
        "aider": os.getenv("AIDER_COMMAND", "aider"),
        "gemini": _GEMINI_COMMAND,
        "claude": os.getenv("CLAUDE_COMMAND", "claude"),
        "shell": os.getenv("DEFAULT_AI_SHELL", "/bin/bash"),
    }
    DEFAULT_AI_TOOL = os.getenv("DEFAULT_AI_TOOL", "claude")
    DEFAULT_AI_SHELL = os.getenv("DEFAULT_AI_SHELL", "/bin/bash")
    DEFAULT_AI_ROWS = _get_int_env_var("DEFAULT_AI_ROWS", 30)
    DEFAULT_AI_COLS = _get_int_env_var("DEFAULT_AI_COLS", 100)
    USE_TMUX_FOR_AI_SESSIONS = os.getenv(
        "USE_TMUX_FOR_AI_SESSIONS", "true"
    ).lower() in {
        "1",
        "true",
        "yes",
    }
    ENABLE_PERSISTENT_SESSIONS = os.getenv(
        "ENABLE_PERSISTENT_SESSIONS", "true"
    ).lower() in {
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
    SEMAPHORE_DEFAULT_PROJECT_ID = _get_int_env_var("SEMAPHORE_DEFAULT_PROJECT_ID", 0)
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
    GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-pro")
    CODEX_CONFIG_DIR = os.getenv("CODEX_CONFIG_DIR", str((Path.home() / ".codex")))
    CLAUDE_CONFIG_DIR = os.getenv("CLAUDE_CONFIG_DIR", str((Path.home() / ".claude")))
    CODEX_UPDATE_COMMAND = os.getenv(
        "CODEX_UPDATE_COMMAND", "npm install -g @openai/codex"
    )
    CODEX_BREW_PACKAGE = os.getenv("CODEX_BREW_PACKAGE", "")
    CODEX_VERSION_COMMAND = os.getenv("CODEX_VERSION_COMMAND", "codex --version")
    CODEX_LATEST_VERSION_COMMAND = os.getenv(
        "CODEX_LATEST_VERSION_COMMAND",
        "npm view @openai/codex version",
    )
    GEMINI_UPDATE_COMMAND = os.getenv(
        "GEMINI_UPDATE_COMMAND", "npm install -g @google/gemini-cli"
    )
    GEMINI_BREW_PACKAGE = os.getenv("GEMINI_BREW_PACKAGE", "")
    GEMINI_VERSION_COMMAND = os.getenv("GEMINI_VERSION_COMMAND", "gemini --version")
    GEMINI_LATEST_VERSION_COMMAND = os.getenv(
        "GEMINI_LATEST_VERSION_COMMAND",
        "npm view @google/gemini-cli version",
    )
    CLAUDE_UPDATE_COMMAND = os.getenv(
        "CLAUDE_UPDATE_COMMAND", "npm install -g @anthropic-ai/claude-code"
    )
    CLAUDE_BREW_PACKAGE = os.getenv("CLAUDE_BREW_PACKAGE", "claude-code")
    CLAUDE_VERSION_COMMAND = os.getenv("CLAUDE_VERSION_COMMAND", "claude --version")
    CLAUDE_LATEST_VERSION_COMMAND = os.getenv(
        "CLAUDE_LATEST_VERSION_COMMAND",
        "npm view @anthropic-ai/claude-code version",
    )
    # Linux user switching for tmux sessions
    USE_LOGIN_SHELL = os.getenv("USE_LOGIN_SHELL", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    LINUX_USER_STRATEGY = os.getenv(
        "LINUX_USER_STRATEGY", "mapping"
    )  # 'mapping' or 'direct'
    # Mapping of aiops user email/username to Linux system usernames
    # Example: {'user@example.com': 'user', 'other@example.com': 'other'}
    # Can be set via LINUX_USER_MAPPING env var as JSON string or loaded from database
    LINUX_USER_MAPPING: dict[str, str] = {}
    _mapping_env = os.getenv("LINUX_USER_MAPPING", "")
    if _mapping_env:
        import json

        try:
            LINUX_USER_MAPPING = json.loads(_mapping_env)
        except (json.JSONDecodeError, ValueError):
            LINUX_USER_MAPPING = {}
