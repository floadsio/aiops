from pathlib import Path
from typing import Optional, Type

from flask import Flask

from .cli import register_cli_commands
from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .routes.api import api_bp
from .routes.admin import admin_bp
from .routes.auth import auth_bp
from .routes.projects import projects_bp


def create_app(
    config_object: Optional[Type[Config]] = None,
    instance_path: Optional[Path] = None,
) -> Flask:
    if instance_path is not None:
        app = Flask(
            __name__, instance_path=str(instance_path), instance_relative_config=True
        )
    else:
        app = Flask(__name__, instance_relative_config=True)
    cfg = config_object or Config
    app.config.from_object(cfg)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    repo_root = Path(app.config["REPO_STORAGE_PATH"])
    repo_root.mkdir(parents=True, exist_ok=True)

    register_extensions(app)
    register_blueprints(app)
    register_cli_commands(app)

    return app


def register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(projects_bp, url_prefix="/projects")
    app.register_blueprint(api_bp)
