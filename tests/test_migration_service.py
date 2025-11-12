from __future__ import annotations

import textwrap

import pytest

from app import create_app, db
from app.config import Config
from app.services.migration_service import MigrationError, run_db_upgrade


class MigrationTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(MigrationTestConfig)
    with application.app_context():
        db.create_all()
    yield application


def test_run_db_upgrade_success(tmp_path, app):
    fake_flask = tmp_path / "fake-flask"
    fake_flask.write_text(
        textwrap.dedent(
            """\
            #!/bin/bash
            echo "Running migrations $@"
            """
        )
    )
    fake_flask.chmod(0o755)

    with app.app_context():
        result = run_db_upgrade(flask_executable=fake_flask)

    assert result.ok is True
    assert "db upgrade" in result.command
    assert "Running migrations --app manage.py db upgrade" in result.stdout


def test_run_db_upgrade_missing_binary(tmp_path, app):
    missing = tmp_path / "missing-flask"
    with app.app_context(), pytest.raises(MigrationError):
        run_db_upgrade(flask_executable=missing)
