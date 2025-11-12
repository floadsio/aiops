from __future__ import annotations

import json

import pytest

from app import create_app
from app.config import Config
from app.services.claude_update_service import get_claude_status


class _Config(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app():
    application = create_app(_Config)
    with application.app_context():
        yield application


def test_get_claude_status_uses_brew_when_npm_missing(monkeypatch, app):
    def fake_run(command, timeout):
        if command[:2] == ["claude", "--version"]:
            return type(
                "Proc",
                (),
                {"returncode": 0, "stdout": "2.0.37 (Claude Code)", "stderr": ""},
            )
        if command[:3] == ["npm", "view", "@anthropic/claude-cli"]:
            return type("Proc", (), {"returncode": 1, "stdout": "", "stderr": "E404"})
        if command[:3] == ["brew", "info", "--json=v2"]:
            payload = {"casks": [{"version": "2.1.0"}]}
            return type(
                "Proc",
                (),
                {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("app.services.claude_update_service._run_command", fake_run)

    with app.app_context():
        status = get_claude_status()
        assert status.installed_version == "2.0.37"
        assert status.latest_version == "2.1.0"
        assert status.update_available is True
