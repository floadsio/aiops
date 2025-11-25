from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.services.ai_issue_generator import (
    AIIssueGenerationError,
    generate_issue_from_description,
)
from app.services.codex_config_service import save_codex_auth


def _build_app(tmp_path: Path, codex_command: str):
    class _Config(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        ALLOWED_AI_TOOLS = {"codex": codex_command}
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")

    instance_dir = tmp_path / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    return create_app(_Config, instance_path=instance_dir)


@pytest.mark.parametrize(
    "codex_command, expected_exec_count",
    [
        ("codex --sandbox danger-full-access --ask-for-approval never", 1),
        ("codex exec --sandbox danger-full-access", 1),
    ],
)
def test_codex_exec_used_for_issue_generation(monkeypatch, tmp_path, codex_command, expected_exec_count):
    """Ensure we call codex with the exec subcommand (no legacy query)."""
    calls: dict = {}

    def fake_run(cmd, capture_output, text, timeout, check, env=None):
        calls["cmd"] = cmd
        calls["env"] = env
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"title":"T","description":"D","labels":["bug"],"branch_prefix":"fix"}',
            stderr="",
        )

    monkeypatch.setattr("app.services.ai_issue_generator.subprocess.run", fake_run)

    app = _build_app(tmp_path, codex_command)
    with app.app_context():
        issue_data = generate_issue_from_description(
            "broken markdown rendering",
            ai_tool="codex",
            issue_type="bug",
        )

    cmd = calls["cmd"]
    assert cmd.count("exec") == expected_exec_count
    assert "query" not in cmd
    assert cmd[-1].startswith("You are helping a developer")
    assert issue_data["branch_prefix"] == "fix"


def test_codex_authentication_env_set_when_user_id_provided(monkeypatch, tmp_path):
    """Ensure CODEX_CONFIG_DIR and CODEX_AUTH_FILE are set when user_id is provided."""
    calls: dict = {}

    def fake_run(cmd, capture_output, text, timeout, check, env=None):
        calls["cmd"] = cmd
        calls["env"] = env
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"title":"T","description":"D","labels":["bug"],"branch_prefix":"fix"}',
            stderr="",
        )

    monkeypatch.setattr("app.services.ai_issue_generator.subprocess.run", fake_run)

    app = _build_app(tmp_path, "codex")
    with app.app_context():
        # Save codex auth for user 42
        save_codex_auth(json.dumps({"token": "test-token"}), user_id=42)

        issue_data = generate_issue_from_description(
            "test description",
            ai_tool="codex",
            issue_type="bug",
            user_id=42,
        )

    env = calls["env"]
    assert env is not None
    assert "CODEX_CONFIG_DIR" in env
    assert "CODEX_AUTH_FILE" in env
    assert ".codex" in env["CODEX_CONFIG_DIR"]
    assert "auth.json" in env["CODEX_AUTH_FILE"]
    assert issue_data["title"] == "T"


def test_codex_auth_failure_raises_ai_issue_generation_error(tmp_path):
    """Ensure CodexConfigError is wrapped in AIIssueGenerationError."""
    app = _build_app(tmp_path, "codex")
    with app.app_context():
        # User 999 has no saved credentials
        with pytest.raises(AIIssueGenerationError) as exc_info:
            generate_issue_from_description(
                "test description",
                ai_tool="codex",
                issue_type="bug",
                user_id=999,
            )

        assert "Codex authentication failed" in str(exc_info.value)
        assert "configure Codex credentials" in str(exc_info.value)
