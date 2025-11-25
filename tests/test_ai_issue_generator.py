from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.services.ai_issue_generator import generate_issue_from_description


def _build_app(tmp_path: Path, codex_command: str):
    class _Config(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        ALLOWED_AI_TOOLS = {"codex": codex_command}

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
