from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import create_app
from app.config import Config
from app.services.ai_cli_update_service import (
    CLICommandError,
    CLICommandResult,
    get_ai_tool_versions,
    run_ai_tool_update,
)


class _TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(tmp_path):
    class LocalConfig(_TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'cli-update.db'}"
        CLI_EXTRA_PATHS = str(tmp_path / "opt" / "bin")

    application = create_app(LocalConfig, instance_path=tmp_path / "instance")
    extra_dir = tmp_path / "opt" / "bin"
    extra_dir.mkdir(parents=True, exist_ok=True)
    application.config["TEST_EXTRA_CLI_PATH"] = str(extra_dir)
    yield application


def test_run_ai_tool_update_invokes_subprocess(app, monkeypatch):
    captured = {}

    def fake_run(parts, **kwargs):
        captured["parts"] = parts
        captured["env"] = kwargs["env"]
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("app.services.ai_cli_update_service.subprocess.run", fake_run)

    with app.app_context():
        result = run_ai_tool_update("codex", "npm")

    assert captured["parts"][0] == "sudo"
    assert "npm" in captured["parts"]
    assert result.ok is True
    assert app.config["TEST_EXTRA_CLI_PATH"] in captured["env"]["PATH"]


def test_run_ai_tool_update_missing_command_raises(app):
    with app.app_context():
        app.config["CODEX_UPDATE_COMMAND"] = ""
        with pytest.raises(CLICommandError):
            run_ai_tool_update("codex", "npm")


def test_run_ai_tool_update_rejects_unknown_source(app):
    with app.app_context():
        with pytest.raises(CLICommandError):
            run_ai_tool_update("codex", "invalid")


def test_get_ai_tool_versions_returns_outputs(app, monkeypatch):
    calls: list[str] = []

    def fake_run(command, *, timeout):
        calls.append(command)
        return CLICommandResult(command, stdout="2.0.0\n", stderr="", returncode=0)

    monkeypatch.setattr(
        "app.services.ai_cli_update_service.run_cli_command",
        fake_run,
    )

    with app.app_context():
        info = get_ai_tool_versions("codex")

    assert info.installed == "2.0.0"
    assert info.latest == "2.0.0"
    assert info.installed_error is None
    assert info.latest_error is None
    assert calls == [
        app.config["CODEX_VERSION_COMMAND"],
        app.config["CODEX_LATEST_VERSION_COMMAND"],
    ]


def test_get_ai_tool_versions_handles_failures(app, monkeypatch):
    def fake_run(command, *, timeout):
        return CLICommandResult(command, stdout="", stderr="boom", returncode=1)

    monkeypatch.setattr(
        "app.services.ai_cli_update_service.run_cli_command",
        fake_run,
    )

    with app.app_context():
        info = get_ai_tool_versions("gemini")

    assert info.installed is None
    assert info.installed_error == "boom"
    assert info.latest is None
    assert info.latest_error == "boom"
