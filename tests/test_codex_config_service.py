from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.services.codex_config_service import (
    CodexConfigError,
    ensure_codex_auth,
    get_user_auth_paths,
    load_codex_auth,
    save_codex_auth,
)


class _Config(Config):
    TESTING = True
    CODEX_CONFIG_DIR = ":memory:"


@pytest.fixture()
def app(tmp_path):
    class _TmpConfig(_Config):
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")

    instance_dir = tmp_path / "instance"
    application = create_app(_TmpConfig, instance_path=instance_dir)
    with application.app_context():
        yield application


def test_save_and_load_codex_auth(app):
    with app.app_context():
        payload = {"token": "abc123"}
        save_codex_auth(json.dumps(payload), user_id=5)
        stored = json.loads(load_codex_auth(user_id=5))
        assert stored == payload
        cli_path, storage_path = get_user_auth_paths(5)
        assert cli_path.exists()
        assert storage_path.exists()


def test_save_codex_auth_requires_user(app):
    with app.app_context():
        with pytest.raises(CodexConfigError):
            save_codex_auth("{}", user_id=None)


def test_save_codex_auth_validates_json(app):
    with app.app_context():
        with pytest.raises(CodexConfigError):
            save_codex_auth("not json", user_id=1)


def test_ensure_requires_stored_payload(app):
    with app.app_context():
        with pytest.raises(CodexConfigError):
            ensure_codex_auth(9)
