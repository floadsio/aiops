from pathlib import Path
from typing import Optional, Type

from flask import Flask, request
from flask_wtf.csrf import generate_csrf  # type: ignore

from .cli import register_cli_commands
from .config import Config
from .constants import DEFAULT_TENANT_COLOR
from .extensions import csrf, db, limiter, login_manager, migrate
from .forms.admin import QuickBranchSwitchForm
from .git_info import detect_repo_branch
from .routes.admin import admin_bp
from .routes.api import api_bp
from .routes.api_v1 import api_v1_bp
from .routes.auth import auth_bp
from .routes.projects import projects_bp
from .services.branch_state import configure_branch_form
from .swagger_config import init_swagger
from .template_utils import register_template_filters
from .version import __version__


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
    register_template_filters(app)
    init_swagger(app)

    app.config.setdefault("AIOPS_VERSION", __version__)

    # Ensure tmux server is running independently
    @app.before_request
    def ensure_tmux_server_once():
        """Ensure tmux server is running on first request."""
        if not hasattr(app, "_tmux_server_started"):
            app._tmux_server_started = True
            try:
                import subprocess
                # Start tmux server if not running (daemonizes automatically)
                subprocess.run(
                    ["tmux", "start-server"],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
                app.logger.info("Tmux server ensured")
            except Exception as exc:  # noqa: BLE001
                app.logger.warning("Failed to ensure tmux server: %s", exc)

    # Scan for recoverable tmux sessions on startup
    @app.before_request
    def scan_orphaned_sessions_once():
        """Scan for orphaned tmux sessions on first request after startup."""
        if not hasattr(app, "_orphaned_sessions_scanned"):
            app._orphaned_sessions_scanned = True
            try:
                from .services.tmux_recovery import scan_and_log_orphaned_sessions, reconnect_persistent_sessions
                scan_and_log_orphaned_sessions()
                # Reconnect persistent sessions if enabled
                if app.config.get("ENABLE_PERSISTENT_SESSIONS", False):
                    reconnect_persistent_sessions()
            except Exception as exc:  # noqa: BLE001
                app.logger.warning("Failed to scan for orphaned sessions: %s", exc)

    return app


def register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    @app.context_processor
    def inject_csrf_token():
        repo_branch = detect_repo_branch(Path(app.root_path).parent)
        branch_switch_form = QuickBranchSwitchForm()
        configure_branch_form(branch_switch_form, current_branch=repo_branch)
        if request:
            branch_switch_form.next.data = request.full_path or request.path
        return {
            "csrf_token": generate_csrf,
            "app_version": app.config.get("AIOPS_VERSION", __version__),
            "app_git_branch": repo_branch or "unknown",
            "default_tenant_color": DEFAULT_TENANT_COLOR,
            "branch_switch_form": branch_switch_form,
        }


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(projects_bp, url_prefix="/projects")
    app.register_blueprint(api_bp)
    app.register_blueprint(api_v1_bp)

    # Exempt API v1 from CSRF since it uses token authentication
    csrf.exempt(api_v1_bp)
