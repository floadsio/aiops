from __future__ import annotations

import json

import pytest

from app import create_app
from app.config import Config
from app.services.gemini_update_service import (
    GeminiUpdateError,
    get_gemini_status,
    install_latest_gemini,
)


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        yield application


def test_get_gemini_status(monkeypatch, app):
    def fake_run(command, timeout):
        if command[:2] == ["gemini", "--version"]:
            return type(
                "Proc",
                (),
                {"returncode": 0, "stdout": "gemini-cli/1.0.0", "stderr": ""},
            )
        if command[:3] == ["npm", "view", "@google/gemini-cli"]:
            return type(
                "Proc", (), {"returncode": 0, "stdout": "1.1.0\n", "stderr": ""}
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("app.services.gemini_update_service._run_command", fake_run)

    with app.app_context():
        status = get_gemini_status()
        assert status.installed_version == "1.0.0"
        assert status.latest_version == "1.1.0"
        assert status.update_available is True
        assert status.errors == ()


def test_get_gemini_status_falls_back_to_npm(monkeypatch, app):
    def fake_run(command, timeout):
        if command[:2] == ["gemini", "--version"]:
            raise FileNotFoundError("gemini missing")
        if command[:3] == ["npm", "list", "-g"]:
            payload = {
                "dependencies": {
                    "@google/gemini-cli": {"version": "1.0.0"},
                }
            }
            return type(
                "Proc",
                (),
                {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
            )
        if command[:3] == ["npm", "view", "@google/gemini-cli"]:
            return type(
                "Proc", (), {"returncode": 0, "stdout": "1.0.0\n", "stderr": ""}
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("app.services.gemini_update_service._run_command", fake_run)

    with app.app_context():
        status = get_gemini_status()
        assert status.installed_version == "1.0.0"
        assert status.latest_version == "1.0.0"
        assert status.update_available is False


def test_install_latest_gemini(monkeypatch, app):
    def fake_run(command, timeout):
        return type(
            "Proc",
            (),
            {
                "returncode": 0,
                "stdout": "ok",
                "stderr": "",
            },
        )

    monkeypatch.setattr("app.services.gemini_update_service._run_command", fake_run)

    with app.app_context():
        result = install_latest_gemini()
        assert result.ok
        assert "@google/gemini-cli" in result.command


def test_install_latest_gemini_handles_error(monkeypatch, app):
    def fake_run(command, timeout):
        raise FileNotFoundError("npm missing")

    monkeypatch.setattr("app.services.gemini_update_service._run_command", fake_run)

    with app.app_context(), pytest.raises(GeminiUpdateError):
        install_latest_gemini()
