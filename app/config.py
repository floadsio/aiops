import os
import shlex
from pathlib import Path

from .version import get_version

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_PATH = str(INSTANCE_DIR.resolve())


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


def _ensure_claude_permission_mode(command: str, permission_mode: str | None) -> str:
    """Add Claude Code permission mode flag if not already present.

    Args:
        command: Base Claude command
        permission_mode: Permission mode - one of:
            - 'acceptEdits': Auto-accept file edits, prompt for dangerous commands (safer)
            - 'yolo': Skip all permissions (dangerous, use in isolated environments)
            - 'prompt': Prompt for all actions (default interactive mode)
            - None or empty: Don't add any permission flag

    Returns:
        Command with permission mode flag appended if needed
    """
    if not command or not permission_mode:
        return command

    try:
        tokens = shlex.split(command)
    except ValueError:
        return command

    # Check if permission mode is already set
    for token in tokens:
        if token in ("--permission-mode", "--dangerously-skip-permissions"):
            return command
        if token.startswith("--permission-mode="):
            return command

    # Add appropriate flag based on mode
    if permission_mode == "yolo":
        tokens.append("--dangerously-skip-permissions")
    elif permission_mode in ("acceptEdits", "prompt"):
        tokens.extend(["--permission-mode", permission_mode])

    return shlex.join(tokens)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SSH_KEY_ENCRYPTION_KEY = os.getenv("SSH_KEY_ENCRYPTION_KEY")
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
    CLI_EXTRA_PATHS = os.getenv("CLI_EXTRA_PATHS", "/opt/homebrew/bin:/usr/local/bin")
    CODEX_SANDBOX_MODE = os.getenv("CODEX_SANDBOX_MODE", "danger-full-access")
    CODEX_APPROVAL_MODE = os.getenv("CODEX_APPROVAL_MODE", "never")
    CLAUDE_PERMISSION_MODE = os.getenv("CLAUDE_PERMISSION_MODE", "acceptEdits")
    _CODEX_COMMAND = _ensure_codex_flags(
        os.getenv("CODEX_COMMAND", "codex"),
        sandbox_mode=CODEX_SANDBOX_MODE,
        approval_mode=CODEX_APPROVAL_MODE,
    )
    _CLAUDE_COMMAND = _ensure_claude_permission_mode(
        os.getenv("CLAUDE_COMMAND", "claude"),
        CLAUDE_PERMISSION_MODE,
    )
    ALLOWED_AI_TOOLS = {
        "codex": _CODEX_COMMAND,
        "aider": os.getenv("AIDER_COMMAND", "aider"),
        "claude": _CLAUDE_COMMAND,
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
    # Base URL for generating links in notifications (e.g., Slack messages)
    AIOPS_BASE_URL = os.getenv("AIOPS_BASE_URL", "")
    GIT_AUTHOR_NAME = os.getenv("GIT_AUTHOR_NAME", "AI Ops Dashboard")
    GIT_AUTHOR_EMAIL = os.getenv("GIT_AUTHOR_EMAIL", "aiops@example.com")
    AIOPS_VERSION = get_version()
    LOG_FILE = os.getenv(
        "LOG_FILE",
        str((BASE_DIR / "logs" / "aiops.log").resolve()),
    )
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
    CLAUDE_UPDATE_COMMAND = os.getenv(
        "CLAUDE_UPDATE_COMMAND", "npm install -g @anthropic-ai/claude-code"
    )
    CLAUDE_BREW_PACKAGE = os.getenv("CLAUDE_BREW_PACKAGE", "claude-code")
    CLAUDE_VERSION_COMMAND = os.getenv("CLAUDE_VERSION_COMMAND", "claude --version")
    CLAUDE_LATEST_VERSION_COMMAND = os.getenv(
        "CLAUDE_LATEST_VERSION_COMMAND",
        "npm view @anthropic-ai/claude-code version",
    )
    # Ollama configuration for AI-assisted issue generation
    OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60.0"))
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
    # Dotfiles (yadm) Configuration
    DOTFILE_REPO_URL = os.getenv("DOTFILE_REPO_URL")
    DOTFILE_REPO_BRANCH = os.getenv("DOTFILE_REPO_BRANCH", "main")
    # Automatic Issue Sync Configuration
    ISSUE_SYNC_ENABLED = os.getenv("ISSUE_SYNC_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    ISSUE_SYNC_INTERVAL = _get_int_env_var("ISSUE_SYNC_INTERVAL", 900)  # 15 minutes
    ISSUE_SYNC_ON_STARTUP = os.getenv("ISSUE_SYNC_ON_STARTUP", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    ISSUE_SYNC_MAX_CONCURRENT = _get_int_env_var("ISSUE_SYNC_MAX_CONCURRENT", 3)

    # Slack Polling Configuration
    SLACK_POLL_ENABLED = os.getenv("SLACK_POLL_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    SLACK_POLL_INTERVAL = _get_int_env_var("SLACK_POLL_INTERVAL", 300)  # 5 minutes
