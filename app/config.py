import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


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
    ALLOWED_AI_TOOLS = {
        "codex": os.getenv("CODEX_COMMAND", "codex"),
        "aider": os.getenv("AIDER_COMMAND", "aider"),
    }
    DEFAULT_AI_TOOL = os.getenv("DEFAULT_AI_TOOL", "codex")
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
    LOG_FILE = os.getenv(
        "LOG_FILE",
        str((BASE_DIR / "logs" / "aiops.log").resolve()),
    )
