from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.services.gemini_config_service import (
    GeminiConfigError,
    ensure_user_config,
    get_config_dir,
    save_google_accounts,
    save_oauth_creds,
    save_settings_json,
    load_google_accounts,
    load_oauth_creds,
    load_settings_json,
)


class _Config(Config):
    TESTING = True
    GEMINI_CONFIG_DIR = ":memory:"


@pytest.fixture()
def app(tmp_path):
    class _TmpConfig(_Config):
        GEMINI_CONFIG_DIR = str(tmp_path / ".gemini")

    instance_dir = tmp_path / "instance"
    application = create_app(_TmpConfig, instance_path=instance_dir)
    with application.app_context():
        yield application


def test_save_google_accounts(app):
    payload = {"accounts": [{"name": "demo"}]}
    with app.app_context():
        save_google_accounts(json.dumps(payload), user_id=7)
    config_dir = get_config_dir(user_id=7)
    storage_dir = Path(app.instance_path) / "gemini" / "user-7"
    contents = json.loads((config_dir / "google_accounts.json").read_text())
    assert contents == payload
    persisted = json.loads((storage_dir / "google_accounts.json").read_text())
    assert persisted == payload
    assert json.loads(load_google_accounts(user_id=7)) == payload


def test_save_oauth_creds_validation(app):
    with app.app_context():
        with pytest.raises(GeminiConfigError):
            save_oauth_creds("not json", user_id=1)
        payload = {"token": "secret"}
        save_oauth_creds(json.dumps(payload), user_id=1)
        config_dir = get_config_dir(user_id=1)
        storage_dir = Path(app.instance_path) / "gemini" / "user-1"
        contents = json.loads((config_dir / "oauth_creds.json").read_text())
        assert contents == payload
        persisted = json.loads((storage_dir / "oauth_creds.json").read_text())
        assert persisted == payload
        assert json.loads(load_oauth_creds(user_id=1)) == payload


def test_load_uses_shared_fallback(app):
    shared_payload = {"token": "shared"}
    with app.app_context():
        legacy_dir = Path(app.config["GEMINI_CONFIG_DIR"]) / "user-99"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "oauth_creds.json").write_text(json.dumps(shared_payload), encoding="utf-8")
        assert json.loads(load_oauth_creds(user_id=99)) == shared_payload


def test_save_settings_json_roundtrip(app):
    payload = {"ui": {"theme": "midnight"}, "model": "gemini-1.5-pro"}
    with app.app_context():
        save_settings_json(json.dumps(payload), user_id=5)
        config_dir = get_config_dir(user_id=5)
        storage_dir = Path(app.instance_path) / "gemini" / "user-5"
        assert json.loads((config_dir / "settings.json").read_text()) == payload
        assert json.loads((storage_dir / "settings.json").read_text()) == payload
        assert json.loads(load_settings_json(user_id=5)) == payload


def test_save_settings_json_validation(app):
    with app.app_context():
        with pytest.raises(GeminiConfigError):
            save_settings_json("not-json", user_id=1)


def test_ensure_user_config_seeds_from_stored_payload(app, tmp_path):
    with app.app_context():
        payload = {"token": "persisted"}
        save_oauth_creds(json.dumps(payload), user_id=11)
        config_dir = get_config_dir(user_id=11)
        # remove CLI copy to simulate missing file
        (config_dir / "oauth_creds.json").unlink()
        ensure_user_config(11)
        restored = json.loads((config_dir / "oauth_creds.json").read_text())
        assert restored == payload


def test_ensure_user_config_seeds_from_shared(app):
    with app.app_context():
        save_google_accounts(json.dumps({"accounts": []}), user_id=42)
        save_oauth_creds(json.dumps({"token": "t"}), user_id=42)
        save_settings_json(json.dumps({"model": "gemini-2.5-flash"}), user_id=42)
        user_dir = ensure_user_config(42)
        accounts = json.loads((user_dir / "google_accounts.json").read_text())
        oauth = json.loads((user_dir / "oauth_creds.json").read_text())
        settings = json.loads((user_dir / "settings.json").read_text())
        assert "accounts" in accounts
        assert oauth["token"] == "t"
        assert settings["model"] == "gemini-2.5-flash"
