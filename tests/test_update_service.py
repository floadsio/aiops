from __future__ import annotations

import pytest

from app import create_app
from app.config import Config
from app.services.update_service import run_update_script, UpdateError


class UpdateTestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False


def test_run_update_script_success(tmp_path):
    script = tmp_path / "update.sh"
    script.write_text("#!/bin/bash\necho 'update-ok'\n", encoding="utf-8")
    script.chmod(0o755)

    app = create_app(UpdateTestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        result = run_update_script(script_path=script)

    assert result.ok
    assert "update-ok" in result.stdout
    assert result.stderr == ""
    assert script.as_posix() in result.command


def test_run_update_script_missing(tmp_path):
    app = create_app(UpdateTestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        with pytest.raises(UpdateError):
            run_update_script(script_path=tmp_path / "missing.sh")
