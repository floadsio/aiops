from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from app import create_app
from app.config import Config
from app.services.codex_update_service import (
    CodexStatus,
    CodexUpdateError,
    get_codex_status,
    install_latest_codex,
)


class CodexTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(tmp_path):
    return create_app(CodexTestConfig, instance_path=tmp_path / "instance")


def test_get_codex_status_signals_update(monkeypatch, app):
    def fake_run(command, timeout):
        if command[:2] == ["codex", "--version"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="codex/1.0.0\n", stderr=""
            )
        if command[:3] == ["npm", "view", "@openai/codex"]:
            return subprocess.CompletedProcess(command, 0, stdout="1.1.0\n", stderr="")
        raise AssertionError(f"Unexpected command {command}")

    monkeypatch.setattr("app.services.codex_update_service._run_command", fake_run)

    with app.app_context():
        status = get_codex_status()

    assert isinstance(status, CodexStatus)
    assert status.installed_version == "1.0.0"
    assert status.latest_version == "1.1.0"
    assert status.update_available is True
    assert not status.errors


def test_get_codex_status_handles_missing_cli(monkeypatch, app):
    def fake_run(command, timeout):
        if command[:2] == ["codex", "--version"]:
            raise FileNotFoundError("codex missing")
        if command[:3] == ["npm", "list", "-g"]:
            payload = {"dependencies": {}}
            return subprocess.CompletedProcess(
                command, 1, stdout=json.dumps(payload), stderr=""
            )
        if command[:3] == ["npm", "view", "@openai/codex"]:
            return subprocess.CompletedProcess(command, 0, stdout="1.1.0\n", stderr="")
        raise AssertionError(f"Unexpected command {command}")

    monkeypatch.setattr("app.services.codex_update_service._run_command", fake_run)

    with app.app_context():
        status = get_codex_status()

    assert status.installed_version is None
    assert status.latest_version == "1.1.0"
    assert status.update_available is False
    assert "Codex CLI is not installed." in status.errors


def test_install_latest_codex_success(monkeypatch, app):
    executed = SimpleNamespace(commands=[])

    def fake_run(command, timeout):
        executed.commands.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="updated", stderr="")

    monkeypatch.setattr("app.services.codex_update_service._run_command", fake_run)

    with app.app_context():
        result = install_latest_codex(timeout=30)

    assert result.ok is True
    assert "updated" in result.stdout
    assert executed.commands
    assert executed.commands[0][0][0] == "sudo"


def test_install_latest_codex_raises_when_command_fails(monkeypatch, app):
    def fake_run(command, timeout):
        raise FileNotFoundError("sudo not found")

    monkeypatch.setattr("app.services.codex_update_service._run_command", fake_run)

    with app.app_context():
        with pytest.raises(CodexUpdateError) as excinfo:
            install_latest_codex(timeout=5)

    assert "Unable to execute Codex update command" in str(excinfo.value)
