from __future__ import annotations

import os
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import subprocess
import threading
import time
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from markupsafe import Markup, escape
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..constants import DEFAULT_TENANT_COLOR, sanitize_tenant_color
from ..extensions import db
from ..forms.admin import (
    ProjectForm,
    ProjectIntegrationDeleteForm,
    ProjectIntegrationForm,
    ProjectIntegrationUpdateForm,
    ProjectIssueSyncForm,
    ProjectGitRefreshForm,
    ProjectBranchForm,
    ProjectDeleteForm,
    UpdateApplicationForm,
    QuickBranchSwitchForm,
    CreateUserForm,
    UserUpdateForm,
    UserToggleAdminForm,
    UserResetPasswordForm,
    UserDeleteForm,
    SSHKeyForm,
    SSHKeyDeleteForm,
    TenantForm,
    TenantAppearanceForm,
    TenantDeleteForm,
    TenantIntegrationForm,
    TenantIntegrationDeleteForm,
    CodexUpdateForm,
    GeminiUpdateForm,
    MigrationRunForm,
    TmuxResyncForm,
)
from ..git_info import list_repo_branches
from ..models import (
    ExternalIssue,
    Project,
    ProjectIntegration,
    SSHKey,
    Tenant,
    TenantIntegration,
    User,
)
from ..services.git_service import (
    ensure_repo_checkout,
    get_repo_status,
    run_git_action,
    checkout_or_create_branch,
    merge_branch,
    delete_project_branch,
    list_project_branches,
)
from ..services.issues import (
    ISSUE_STATUS_MAX_LENGTH,
    IssueSyncError,
    IssueUpdateError,
    test_integration_connection,
    sync_project_integration,
    sync_tenant_integrations,
    update_issue_status as update_issue_status_service,
)
from ..services.issues.utils import normalize_issue_status
from ..services.tmux_service import (
    TmuxServiceError,
    list_windows_for_aliases,
    sync_project_windows,
    TmuxSyncResult,
    session_name_for_user,
)
from ..services.key_service import compute_fingerprint, format_private_key_path, resolve_private_key_path
from ..services.update_service import run_update_script, UpdateError
from ..services.migration_service import run_db_upgrade, MigrationError
from ..services.codex_update_service import (
    CodexStatus,
    CodexUpdateError,
    get_codex_status,
    install_latest_codex,
)
from ..services.gemini_update_service import (
    GeminiStatus,
    GeminiUpdateError,
    get_gemini_status,
    install_latest_gemini,
)
from ..services.agent_context import (
    MISSING_ISSUE_DETAILS_MESSAGE,
    extract_issue_description,
)
from ..services.log_service import read_log_tail, LogReadError
from ..services.branch_state import (
    configure_branch_form,
    remember_branch,
    current_repo_branch,
    switch_repo_branch,
    BranchSwitchError,
)
from ..security import hash_password

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")


def admin_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Administrator access required.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    return login_required(wrapper)


def _private_key_dir() -> Path:
    path = Path(current_app.instance_path) / "keys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _truncate_output(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… (truncated)"


def _issue_sort_key(issue: ExternalIssue):
    reference = issue.external_updated_at or issue.updated_at or issue.created_at
    if reference is None:
        reference = datetime.min.replace(tzinfo=timezone.utc)
    elif reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference


def _format_issue_timestamp(value):
    if value is None:
        return None
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone().strftime("%b %d, %Y • %H:%M %Z")


ISSUE_SORT_COLUMNS = (
    {"key": "external_id", "label": "ID", "default_direction": "asc"},
    {"key": "title", "label": "Title", "default_direction": "asc"},
    {"key": "status", "label": "Status", "default_direction": "asc"},
    {"key": "provider", "label": "Provider", "default_direction": "asc"},
    {"key": "project", "label": "Project", "default_direction": "asc"},
    {"key": "tenant", "label": "Tenant", "default_direction": "asc"},
    {"key": "updated", "label": "Updated", "default_direction": "desc"},
    {"key": "assignee", "label": "Assignee", "default_direction": "asc"},
    {"key": "labels", "label": "Labels", "default_direction": "asc"},
)
ISSUE_SORT_DEFAULT_KEY = "updated"
ISSUE_SORT_META = {column["key"]: column for column in ISSUE_SORT_COLUMNS}


def _trigger_restart(restart_command: str | None) -> tuple[bool, str]:
    """
    Attempt to restart the application process.

    Returns a (success, message) tuple suitable for flashing in the UI.
    """
    if restart_command:
        try:
            subprocess.Popen(
                restart_command,
                shell=True,
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return False, f"Failed to execute restart command: {exc}"
        return True, f"Executed restart command: {restart_command}"

    shutdown_func = request.environ.get("werkzeug.server.shutdown")
    if shutdown_func:
        threading.Thread(target=shutdown_func, daemon=True).start()
        return True, "Werkzeug server shutting down to apply updates."

    def _delayed_exit():
        time.sleep(1.0)
        os._exit(3)

    threading.Thread(target=_delayed_exit, daemon=True).start()
    return True, "Application process will exit shortly to allow supervisor restart."


def _remove_private_key_file(ssh_key: SSHKey) -> None:
    if not ssh_key.private_key_path:
        return
    try:
        path_obj = resolve_private_key_path(ssh_key.private_key_path)
        if path_obj and path_obj.exists():
            path_obj.unlink()
    except OSError as exc:
        current_app.logger.warning(
            "Failed to remove private key file %s: %s", ssh_key.private_key_path, exc
        )
    ssh_key.private_key_path = None


def _store_private_key_file(ssh_key: SSHKey, private_key: str) -> None:
    sanitized = private_key.strip()
    if not sanitized:
        return
    destination_dir = _private_key_dir()
    filename = f"sshkey-{ssh_key.id}.pem"
    destination = destination_dir / filename

    existing_path = (
        resolve_private_key_path(ssh_key.private_key_path) if ssh_key.private_key_path else None
    )
    if existing_path and existing_path.exists() and existing_path != destination:
        try:
            existing_path.unlink()
        except OSError:
            current_app.logger.warning("Unable to remove previous private key file %s", existing_path)

    if destination.exists():
        try:
            destination.unlink()
        except OSError:
            current_app.logger.warning("Unable to remove existing private key file %s", destination)

    try:
        with destination.open("w", encoding="utf-8") as handle:
            handle.write(sanitized)
            if not sanitized.endswith("\n"):
                handle.write("\n")
        os.chmod(destination, 0o600)
    except OSError as exc:
        current_app.logger.error("Failed to store private key for %s: %s", ssh_key.name, exc)
        raise

    ssh_key.private_key_path = format_private_key_path(destination)


def _coerce_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _current_tmux_session_name() -> str:
    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    return session_name_for_user(user_obj)


@admin_bp.route("/")
@admin_required
def dashboard():
    search_query = ""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        search_query = (payload.get("q") or "").strip()
    else:
        search_query = (request.args.get("q") or "").strip()
    like_pattern = f"%{search_query}%"
    search_lower = search_query.lower()

    def _contains_query(value: str | None) -> bool:
        if not search_lower:
            return False
        return search_lower in (value or "").lower()

    def _project_matches_query(project: Project, windows: list[dict[str, Any]]) -> bool:
        return any(
            _contains_query(field)
            for field in (
                project.name,
                project.description,
                project.repo_url,
                project.tenant.name if project.tenant else None,
            )
        ) or _tmux_windows_match(windows)

    def _tmux_windows_match(windows: list[dict[str, Any]]) -> bool:
        return any(
            _contains_query(item)
            for window in windows
            for item in (
                window.get("window"),
                window.get("session"),
                window.get("project_name"),
            )
        )

    tenant_query = Tenant.query
    if search_query:
        tenant_query = tenant_query.filter(
            or_(
                Tenant.name.ilike(like_pattern),
                Tenant.description.ilike(like_pattern),
            )
        )
    tenants = tenant_query.order_by(Tenant.name).all()

    update_form = UpdateApplicationForm()
    update_form.next.data = url_for("admin.dashboard")
    tmux_scope = (request.args.get("tmux_scope") or "mine").strip().lower()
    tmux_scope_show_all = tmux_scope == "all"
    tmux_scope_label = "All users" if tmux_scope_show_all else "My sessions"
    toggle_params = request.args.to_dict(flat=True)
    if tmux_scope_show_all:
        toggle_params.pop("tmux_scope", None)
        tmux_scope_toggle_label = "Show only my sessions"
    else:
        toggle_params["tmux_scope"] = "all"
        tmux_scope_toggle_label = "Show all users"
    tmux_scope_toggle_url = url_for("admin.dashboard", **toggle_params)
    search_endpoint_kwargs: dict[str, str] = {}
    if tmux_scope_show_all:
        search_endpoint_kwargs["tmux_scope"] = "all"
    dashboard_search_endpoint = url_for("admin.dashboard", **search_endpoint_kwargs)

    project_query = Project.query.options(
        selectinload(Project.tenant),
        selectinload(Project.issue_integrations).selectinload(ProjectIntegration.integration),
        selectinload(Project.issue_integrations).selectinload(ProjectIntegration.issues),
    )
    project_limit_default = current_app.config.get("DASHBOARD_PROJECT_LIMIT", 10)
    project_limit_search = current_app.config.get("DASHBOARD_SEARCH_PROJECT_LIMIT", 25)
    project_limit = project_limit_search if search_query else project_limit_default
    projects = project_query.order_by(Project.created_at.desc()).limit(project_limit).all()
    project_cards: list[dict[str, Any]] = []
    recent_tmux_windows: list[dict[str, Any]] = []
    recent_tmux_error: str | None = None
    window_project_map: dict[str, dict[str, Any]] = {}
    tmux_session_name = _current_tmux_session_name()

    def _status_sort_key(item: tuple[str, str]) -> tuple[int, str]:
        key, label = item
        if key == "open":
            priority = 0
        elif key == "closed":
            priority = 1
        elif key == "__none__":
            priority = 2
        else:
            priority = 3
        return priority, label.lower()

    for project in projects:
        status = get_repo_status(project)
        last_activity = _coerce_timestamp(getattr(project, "updated_at", None)) or _coerce_timestamp(
            getattr(project, "created_at", None)
        )
        status_last_commit = _coerce_timestamp(status.get("last_commit_timestamp"))
        if status_last_commit and (last_activity is None or status_last_commit > last_activity):
            last_activity = status_last_commit
        status_last_pull = _coerce_timestamp(status.get("last_pull"))
        if status_last_pull and (last_activity is None or status_last_pull > last_activity):
            last_activity = status_last_pull

        issue_sync_form = ProjectIssueSyncForm()
        issue_sync_form.project_id.data = str(project.id)
        git_refresh_form = ProjectGitRefreshForm()
        git_refresh_form.project_id.data = str(project.id)
        tmux_windows: list[dict[str, Any]] = []
        tmux_error: str | None = None
        try:
            tenant = project.tenant
            tenant_name = tenant.name if tenant else "Unassigned"
            tenant_color = tenant.color if tenant and tenant.color else DEFAULT_TENANT_COLOR
            windows = list_windows_for_aliases(
                "",
                project_local_path=project.local_path,
                extra_aliases=(project.name, getattr(project, "slug", None)),
                session_name=tmux_session_name,
                include_all_sessions=tmux_scope_show_all,
            )
            windows = sorted(
                windows,
                key=lambda w: w.created or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            for window in windows:
                window_name = (getattr(window, "window_name", "") or "").strip()
                if window_name.lower() == "zsh":
                    continue
                session_name = (getattr(window, "session_name", "") or "").strip()
                window_created = _coerce_timestamp(window.created)
                if window_created and (last_activity is None or window_created > last_activity):
                    last_activity = window_created
                tmux_windows.append(
                    {
                        "session": window.session_name,
                        "window": window_name,
                        "target": window.target,
                        "panes": window.panes,
                        "created": window.created,
                        "created_display": (
                            window_created.astimezone().strftime("%b %d, %Y • %H:%M %Z")
                            if window_created
                            else None
                        ),
                        "project_id": project.id,
                        "project_name": project.name,
                        "tenant_name": tenant_name,
                        "tenant_color": tenant_color,
                    }
                )
                window_project_map.setdefault(
                    window.target,
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "tenant_name": tenant_name,
                        "tenant_color": tenant_color,
                    },
                )
        except TmuxServiceError as exc:
            tmux_error = str(exc)

        integration_summaries: list[dict[str, Any]] = []
        aggregate_counts: Counter[str] = Counter()
        aggregate_labels: dict[str, str] = {}
        for link in project.issue_integrations:
            integration = link.integration
            provider_key = (
                (integration.provider or "unknown").lower()
                if integration and integration.provider
                else "unknown"
            )
            provider_display = {
                "gitlab": "GitLab",
                "github": "GitHub",
                "jira": "Jira",
            }.get(
                provider_key,
                (integration.provider or "Unknown").title() if integration else "Unknown",
            )
            base_url = integration.base_url if integration else None
            source_label = (
                base_url
                if base_url
                else (
                    f"Default {provider_display} host"
                    if provider_key not in {"", "unknown"}
                    else "Unknown source"
                )
            )
            status_counts: Counter[str] = Counter()
            status_labels: dict[str, str] = {}
            for issue in link.issues:
                status_key, status_label = normalize_issue_status(issue.status)
                status_counts[status_key] += 1
                status_labels.setdefault(status_key, status_label)
                aggregate_counts[status_key] += 1
                aggregate_labels.setdefault(status_key, status_label)
            total_issues = sum(status_counts.values())
            status_entries: list[dict[str, Any]] = []
            for key, label in sorted(status_labels.items(), key=_status_sort_key):
                count = status_counts.get(key, 0)
                if not count:
                    continue
                status_entries.append(
                    {
                        "key": key,
                        "label": label,
                        "count": count,
                    }
                )

            integration_last_synced = _coerce_timestamp(link.last_synced_at)
            if integration_last_synced and (last_activity is None or integration_last_synced > last_activity):
                last_activity = integration_last_synced

            integration_summaries.append(
                {
                    "integration_name": integration.name if integration else "Unknown integration",
                    "provider_key": provider_key,
                    "provider_display": provider_display,
                    "project_identifier": link.external_identifier,
                    "enabled": integration.enabled if integration else False,
                    "status_entries": status_entries,
                    "total": total_issues,
                    "source_label": source_label,
                }
            )

        issue_summary_entries: list[dict[str, Any]] = []
        for key, label in sorted(aggregate_labels.items(), key=_status_sort_key):
            count = aggregate_counts.get(key, 0)
            if not count:
                continue
            issue_summary_entries.append(
                {
                    "key": key,
                    "label": label,
                    "count": count,
                }
            )

        matches_query = _project_matches_query(project, tmux_windows) if search_query else True
        if search_query and not matches_query:
            continue

        branch_form = ProjectBranchForm(formdata=None)
        branch_form.project_id.data = str(project.id)
        branch_form.branch_name.data = status.get("branch") or project.default_branch
        branch_form.base_branch.data = project.default_branch
        branch_form.merge_source.data = status.get("branch") or project.default_branch
        branch_form.merge_target.data = project.default_branch
        git_refresh_form.branch.data = status.get("branch") or project.default_branch
        try:
            branch_choices = list_project_branches(project)
        except RuntimeError as exc:
            current_app.logger.warning(
                "Failed to list branches for project %s: %s", project.name, exc
            )
            branch_choices = [project.default_branch] if project.default_branch else []

        project_cards.append(
            {
                "project": project,
                "status": status,
                "tmux_windows": tmux_windows,
                "tmux_error": tmux_error,
                "issue_integrations": integration_summaries,
                "issue_summary": {
                    "total": sum(aggregate_counts.values()),
                    "entries": issue_summary_entries,
                },
                "issue_sync_form": issue_sync_form,
                "git_refresh_form": git_refresh_form,
                "branch_form": branch_form,
                "branch_choices": branch_choices,
                "last_activity": last_activity or datetime.min.replace(tzinfo=timezone.utc),
            }
        )
    project_cards.sort(key=lambda card: card.get("last_activity") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    try:
        all_windows = list_windows_for_aliases(
            "",
            session_name=tmux_session_name,
            include_all_sessions=tmux_scope_show_all,
        )
        all_windows = sorted(
            all_windows,
            key=lambda window: window.created or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        max_windows = current_app.config.get("TMUX_RECENT_WINDOW_LIMIT", 8)
        for window in all_windows[:max_windows]:
            window_name = (getattr(window, "window_name", "") or "").strip()
            if window_name.lower() == "zsh":
                continue
            created_display = (
                window.created.astimezone().strftime("%b %d, %Y • %H:%M %Z")
                if window.created
                else None
            )
            recent_tmux_windows.append(
                {
                    "session": window.session_name,
                    "window": window_name,
                    "target": window.target,
                    "panes": window.panes,
                    "created": window.created,
                    "created_display": created_display,
                    "project": window_project_map.get(window.target),
                }
            )
    except TmuxServiceError as exc:
        recent_tmux_error = str(exc)

    if search_query:
        def _recent_tmux_matches(entry: dict[str, Any]) -> bool:
            project_info = entry.get("project") or {}
            return any(
                _contains_query(field)
                for field in (
                    entry.get("window"),
                    entry.get("session"),
                    project_info.get("project_name"),
                )
            )

        recent_tmux_windows = [entry for entry in recent_tmux_windows if _recent_tmux_matches(entry)]

    pending_tasks = sum(p for p in [0])  # placeholder for task count
    return render_template(
        "admin/dashboard.html",
        tenants=tenants,
        projects=projects,
        project_cards=project_cards,
        pending_tasks=pending_tasks,
        recent_tmux_windows=recent_tmux_windows,
        recent_tmux_error=recent_tmux_error,
        update_form=update_form,
        dashboard_query=search_query,
        tmux_scope_show_all=tmux_scope_show_all,
        tmux_scope_label=tmux_scope_label,
        tmux_scope_toggle_url=tmux_scope_toggle_url,
        tmux_scope_toggle_label=tmux_scope_toggle_label,
        dashboard_search_endpoint=dashboard_search_endpoint,
    )


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def manage_settings():
    update_form = UpdateApplicationForm()
    update_form.next.data = url_for("admin.manage_settings")
    current_branch = current_repo_branch()
    configure_branch_form(update_form, current_branch=current_branch)

    codex_update_form = CodexUpdateForm()
    codex_update_form.next.data = url_for("admin.manage_settings")

    gemini_update_form = GeminiUpdateForm()
    gemini_update_form.next.data = url_for("admin.manage_settings")

    migration_form = MigrationRunForm()
    migration_form.next.data = url_for("admin.manage_settings")

    tmux_resync_form = TmuxResyncForm()
    tmux_resync_form.next.data = url_for("admin.manage_settings")

    try:
        codex_status = get_codex_status()
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Unable to determine Codex CLI status.")
        codex_status = CodexStatus(
            installed_version=None,
            latest_version=None,
            update_available=False,
            errors=(f"Unable to determine Codex status: {exc}",),
        )
    try:
        gemini_status = get_gemini_status()
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Unable to determine Gemini CLI status.")
        gemini_status = GeminiStatus(
            installed_version=None,
            latest_version=None,
            update_available=False,
            errors=(f"Unable to determine Gemini status: {exc}",),
        )

    quick_branch_form = QuickBranchSwitchForm()
    quick_branch_form.next.data = url_for("admin.manage_settings")
    configure_branch_form(quick_branch_form, current_branch=current_branch)

    create_user_form = CreateUserForm()
    if create_user_form.submit.data:
        if create_user_form.validate_on_submit():
            name = (create_user_form.name.data or "").strip()
            email = (create_user_form.email.data or "").strip().lower()

            if not name:
                create_user_form.name.errors.append("Full Name is required.")
                flash("Unable to create user. Please correct the errors below.", "danger")
            else:
                user = User(
                    email=email,
                    name=name,
                    password_hash=hash_password(create_user_form.password.data),
                    is_admin=create_user_form.is_admin.data,
                )
                db.session.add(user)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    create_user_form.email.errors.append("A user with this email already exists.")
                    flash("Unable to create user. Please correct the errors below.", "danger")
                else:
                    status = "Administrator" if user.is_admin else "Standard user"
                    flash(f"Created {status.lower()} account for {user.email}.", "success")
                    return redirect(url_for("admin.manage_settings"))
        else:
            flash("Unable to create user. Please correct the errors below.", "danger")

    users = User.query.order_by(User.email).all()
    user_toggle_forms = {
        user.id: UserToggleAdminForm(user_id=str(user.id)) for user in users
    }
    user_reset_forms = {
        user.id: UserResetPasswordForm(user_id=str(user.id)) for user in users
    }
    user_delete_forms = {
        user.id: UserDeleteForm(user_id=str(user.id)) for user in users
    }
    user_update_forms = {}
    for user in users:
        form = UserUpdateForm(formdata=None)
        form.user_id.data = str(user.id)
        form.name.data = user.name
        form.email.data = user.email
        form.is_admin.data = user.is_admin
        user_update_forms[user.id] = form

    return render_template(
        "admin/settings.html",
        update_form=update_form,
        migration_form=migration_form,
        tmux_resync_form=tmux_resync_form,
        create_user_form=create_user_form,
        users=users,
        user_toggle_forms=user_toggle_forms,
        user_reset_forms=user_reset_forms,
        user_delete_forms=user_delete_forms,
        user_update_forms=user_update_forms,
        restart_command=current_app.config.get("UPDATE_RESTART_COMMAND"),
        log_file=current_app.config.get("LOG_FILE"),
        codex_status=codex_status,
        codex_update_form=codex_update_form,
        gemini_status=gemini_status,
        gemini_update_form=gemini_update_form,
        quick_branch_form=quick_branch_form,
    )


@admin_bp.route("/system/update", methods=["POST"])
@admin_required
def run_system_update():
    form = UpdateApplicationForm()
    configure_branch_form(form, current_branch=current_repo_branch())
    if not form.validate_on_submit():
        flash("Invalid update request.", "danger")
        return redirect(url_for("admin.dashboard"))

    restart_requested = bool(form.restart.data)
    branch_override = (form.branch.data or "").strip()
    env_overrides = {}
    if branch_override:
        env_overrides["AIOPS_UPDATE_BRANCH"] = branch_override
    remember_branch(branch_override or current_repo_branch())

    try:
        result = run_update_script(extra_env=env_overrides or None)
    except UpdateError as exc:
        current_app.logger.exception("Application update failed to start.")
        flash(str(exc), "danger")
    else:
        combined_output = "\n".join(
            part for part in [result.stdout.strip(), result.stderr.strip()] if part
        )
        truncated = _truncate_output(combined_output)
        message = (
            f"Update succeeded (exit {result.returncode})."
            if result.ok
            else f"Update failed (exit {result.returncode})."
        )
        category = "success" if result.ok else "danger"
        log_message = f"Application update command finished with exit {result.returncode}"
        if combined_output:
            current_app.logger.info("%s; output: %s", log_message, combined_output)
        else:
            current_app.logger.info(log_message)
        if truncated:
            flash(
                Markup(
                    f"{escape(message)}<pre class=\"update-log\">{escape(truncated)}</pre>"
                ),
                category,
            )
        else:
            flash(message, category)

        if result.ok and restart_requested:
            restart_command = current_app.config.get("UPDATE_RESTART_COMMAND")
            restart_success, restart_message = _trigger_restart(restart_command)
            restart_category = "info" if restart_success else "danger"
            flash(restart_message, restart_category)

    redirect_target = form.next.data or url_for("admin.dashboard")
    return redirect(redirect_target)


@admin_bp.route("/system/quick-branch", methods=["POST"])
@admin_required
def quick_branch_switch():
    form = QuickBranchSwitchForm()
    configure_branch_form(form, current_branch=current_repo_branch())
    if not form.validate_on_submit():
        flash("Invalid branch switch request.", "danger")
        return redirect(form.next.data or url_for("admin.dashboard"))

    branch = (form.branch.data or "").strip()
    if not branch:
        flash("Select a branch to switch to.", "warning")
        return redirect(form.next.data or url_for("admin.dashboard"))

    try:
        switch_repo_branch(branch)
    except BranchSwitchError as exc:
        flash(str(exc), "danger")
        return redirect(form.next.data or url_for("admin.dashboard"))

    remember_branch(branch)
    flash(f"Checked out branch {branch}.", "success")

    restart_command = current_app.config.get("UPDATE_RESTART_COMMAND")
    if restart_command:
        success, restart_message = _trigger_restart(restart_command)
        flash(restart_message, "info" if success else "danger")
    else:
        flash("Branch switched. Restart manually to apply changes.", "warning")

    return redirect(form.next.data or url_for("admin.dashboard"))


@admin_bp.route("/settings/migrations/run", methods=["POST"])
@admin_required
def run_database_migrations():
    form = MigrationRunForm()
    if not form.validate_on_submit():
        flash("Invalid migration request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        result = run_db_upgrade()
    except MigrationError as exc:
        current_app.logger.exception("Database migration run failed to start.")
        flash(str(exc), "danger")
    else:
        combined_output = "\n".join(
            part for part in [result.stdout.strip(), result.stderr.strip()] if part
        )
        truncated = _truncate_output(combined_output)
        message = (
            f"Database migrations succeeded (exit {result.returncode})."
            if result.ok
            else f"Database migrations failed (exit {result.returncode})."
        )
        category = "success" if result.ok else "danger"
        log_message = f"Database migration command finished with exit {result.returncode}"
        if combined_output:
            current_app.logger.info("%s; output: %s", log_message, combined_output)
        else:
            current_app.logger.info(log_message)
        if truncated:
            flash(
                Markup(
                    f"{escape(message)}<pre class=\"update-log\">{escape(truncated)}</pre>"
                ),
                category,
            )
        else:
            flash(message, category)

    redirect_target = form.next.data or url_for("admin.manage_settings")
    return redirect(redirect_target)


@admin_bp.route("/settings/tmux/resync", methods=["POST"])
@admin_required
def resync_tmux_sessions():
    form = TmuxResyncForm()
    if not form.validate_on_submit():
        flash("Invalid tmux resync request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        projects = Project.query.options(selectinload(Project.tenant)).all()
        result = sync_project_windows(
            projects,
            session_name=_current_tmux_session_name(),
        )
    except TmuxServiceError as exc:
        current_app.logger.exception("Failed to resync tmux sessions.")
        flash(str(exc), "danger")
    else:
        flash(
            f"Synced tmux windows for {result.total_managed} project(s); "
            f"created {result.created}, removed {result.removed}.",
            "success",
        )

    redirect_target = form.next.data or url_for("admin.manage_settings")
    return redirect(redirect_target)


@admin_bp.route("/settings/codex/update", methods=["POST"])
@admin_required
def update_codex_cli():
    form = CodexUpdateForm()
    if not form.validate_on_submit():
        flash("Invalid Codex update request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        result = install_latest_codex()
    except CodexUpdateError as exc:
        current_app.logger.exception("Failed to run Codex CLI update.")
        flash(str(exc), "danger")
    else:
        combined_output = "\n".join(
            part for part in [result.stdout.strip(), result.stderr.strip()] if part
        )
        truncated = _truncate_output(combined_output)
        message = (
            f"Codex CLI update succeeded (exit {result.returncode})."
            if result.ok
            else f"Codex CLI update failed (exit {result.returncode})."
        )
        category = "success" if result.ok else "danger"
        log_message = f"Codex CLI update command finished with exit {result.returncode}"
        if combined_output:
            current_app.logger.info("%s; output: %s", log_message, combined_output)
        else:
            current_app.logger.info(log_message)
        if truncated:
            flash(
                Markup(
                    f"{escape(message)}<pre class=\"update-log\">{escape(truncated)}</pre>"
                ),
                category,
            )
        else:
            flash(message, category)

    redirect_target = form.next.data or url_for("admin.manage_settings")
    return redirect(redirect_target)


@admin_bp.route("/settings/gemini/update", methods=["POST"])
@admin_required
def update_gemini_cli():
    form = GeminiUpdateForm()
    if not form.validate_on_submit():
        flash("Invalid Gemini update request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        result = install_latest_gemini()
    except GeminiUpdateError as exc:
        current_app.logger.exception("Failed to run Gemini CLI update.")
        flash(str(exc), "danger")
    else:
        combined_output = "\n".join(
            part for part in [result.stdout.strip(), result.stderr.strip()] if part
        )
        truncated = _truncate_output(combined_output)
        message = (
            f"Gemini CLI update succeeded (exit {result.returncode})."
            if result.ok
            else f"Gemini CLI update failed (exit {result.returncode})."
        )
        category = "success" if result.ok else "danger"
        log_message = f"Gemini CLI update command finished with exit {result.returncode}"
        if combined_output:
            current_app.logger.info("%s; output: %s", log_message, combined_output)
        else:
            current_app.logger.info(log_message)
        if truncated:
            flash(
                Markup(
                    f"{escape(message)}<pre class=\"update-log\">{escape(truncated)}</pre>"
                ),
                category,
            )
        else:
            flash(message, category)

    redirect_target = form.next.data or url_for("admin.manage_settings")
    return redirect(redirect_target)


@admin_bp.route("/settings/logs", methods=["GET"])
@admin_required
def fetch_application_logs():
    try:
        requested_lines = int(request.args.get("lines", "400"))
    except ValueError:
        requested_lines = 400
    requested_lines = max(1, min(requested_lines, 2000))

    log_path_raw = current_app.config.get("LOG_FILE") or "/tmp/aiops.log"
    log_path = Path(log_path_raw)

    try:
        tail = read_log_tail(log_path, max_lines=requested_lines)
    except LogReadError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "content": tail.content,
        "truncated": tail.truncated,
        "path": str(log_path),
    })


@admin_bp.route("/settings/users/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def toggle_user_admin(user_id: int):
    form = UserToggleAdminForm()
    if not form.validate_on_submit() or int(form.user_id.data) != user_id:
        flash("Invalid admin update request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    user = User.query.get_or_404(user_id)
    admin_count = User.query.filter_by(is_admin=True).count()

    if user.is_admin and admin_count <= 1:
        flash("At least one administrator must remain.", "danger")
        return redirect(url_for("admin.manage_settings"))

    user.is_admin = not user.is_admin
    db.session.commit()
    role = "administrator" if user.is_admin else "standard user"
    flash(f"{user.email} is now a {role}.", "success")
    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_user_password(user_id: int):
    form = UserResetPasswordForm()
    if not form.validate_on_submit() or int(form.user_id.data) != user_id:
        flash("Invalid password reset request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    user = User.query.get_or_404(user_id)
    user.password_hash = hash_password(form.password.data)
    db.session.commit()
    flash(f"Password reset for {user.email}.", "success")
    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id: int):
    form = UserDeleteForm()
    if not form.validate_on_submit() or int(form.user_id.data) != user_id:
        flash("Invalid delete request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    user = User.query.get_or_404(user_id)
    admin_count = User.query.filter_by(is_admin=True).count()
    if user.is_admin and admin_count <= 1:
        flash("Cannot delete the last administrator.", "danger")
        return redirect(url_for("admin.manage_settings"))

    db.session.delete(user)
    db.session.commit()
    flash(f"Deleted user {user.email}.", "success")
    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/users/<int:user_id>/update", methods=["POST"])
@admin_required
def update_user(user_id: int):
    form = UserUpdateForm()
    if not form.validate_on_submit():
        error_messages = [message for messages in form.errors.values() for message in messages]
        if error_messages:
            for message in error_messages:
                flash(message, "danger")
        else:
            flash("Invalid user update request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        submitted_id = int(form.user_id.data)
    except (TypeError, ValueError):
        flash("Invalid user update request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    if submitted_id != user_id:
        flash("Invalid user update request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    user = User.query.get_or_404(user_id)
    name = (form.name.data or "").strip()
    email_input = (form.email.data or "").strip()
    normalized_email = email_input.lower()

    if not name:
        flash("Full Name is required.", "danger")
        return redirect(url_for("admin.manage_settings"))

    if user.is_admin and not form.is_admin.data:
        admin_count = User.query.filter_by(is_admin=True).count()
        if admin_count <= 1:
            flash("At least one administrator must remain.", "danger")
            return redirect(url_for("admin.manage_settings"))

    user.name = name
    user.email = normalized_email
    user.is_admin = form.is_admin.data

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("A user with this email already exists.", "danger")
    else:
        flash(f"Updated account for {user.email}.", "success")

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/projects/<int:project_id>/refresh-issues", methods=["POST"])
@admin_required
def refresh_project_issues(project_id: int):
    form = ProjectIssueSyncForm()
    if not form.validate_on_submit() or str(project_id) != (form.project_id.data or ""):
        flash("Invalid issue refresh request.", "danger")
        return redirect(url_for("admin.dashboard"))

    project = Project.query.options(
        selectinload(Project.issue_integrations).selectinload(ProjectIntegration.integration),
    ).get_or_404(project_id)

    force_full = bool(request.form.get("force_full"))

    try:
        total_synced = 0
        for link in project.issue_integrations:
            updated = sync_project_integration(link, force_full=force_full)
            total_synced += len(updated)
        db.session.commit()
    except IssueSyncError as exc:
        db.session.rollback()
        flash(f"Issue refresh failed: {exc}", "danger")
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Issue refresh failed for project_id=%s", project_id)
        flash("Unexpected error while refreshing issues.", "danger")
    else:
        if total_synced:
            flash(f"Refreshed issues for {project.name} ({total_synced} updated).", "success")
        elif force_full:
            flash(f"Refreshed issues for {project.name}. No new updates detected.", "success")
        else:
            flash(f"Issue cache for {project.name} is up to date.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/projects/<int:project_id>/git-refresh", methods=["POST"])
@admin_required
def refresh_project_git(project_id: int):
    form = ProjectGitRefreshForm()
    if not form.validate_on_submit() or str(project_id) != (form.project_id.data or ""):
        flash("Invalid git refresh request.", "danger")
        return redirect(url_for("admin.dashboard"))

    project = Project.query.get_or_404(project_id)
    clean_requested = bool(form.clean_submit.data)
    branch_name = (form.branch.data or "").strip() or None
    try:
        output = run_git_action(project, "pull", ref=branch_name, clean=clean_requested)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Git pull failed for project_id=%s", project_id)
        flash(f"Git pull failed: {exc}", "danger")
    else:
        if clean_requested:
            flash(f"Clean pull completed for {project.name}.", "success")
        else:
            branch_label = branch_name or project.default_branch
            flash(f"Pulled latest changes for {project.name} ({branch_label}).", "success")
        current_app.logger.info(
            "Git pull for project %s (clean=%s): %s", project.name, clean_requested, output
        )
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/projects/<int:project_id>/branch/manage", methods=["POST"])
@admin_required
def manage_project_branch(project_id: int):
    form = ProjectBranchForm()
    if not form.validate_on_submit() or str(project_id) != (form.project_id.data or ""):
        flash("Invalid branch request.", "danger")
        return redirect(url_for("admin.dashboard"))

    project = Project.query.get_or_404(project_id)
    if form.checkout_submit.data:
        branch_name = (form.branch_name.data or "").strip()
        base_branch = (form.base_branch.data or project.default_branch or "").strip()
        if not branch_name:
            flash("Branch name is required.", "danger")
            return redirect(url_for("admin.dashboard"))
        try:
            created = checkout_or_create_branch(project, branch_name, base_branch)
        except RuntimeError as exc:
            flash(str(exc), "danger")
        else:
            action = "Created" if created else "Checked out"
            flash(f"{action} branch {branch_name} for {project.name}.", "success")
        return redirect(url_for("admin.dashboard"))

    if form.merge_submit.data:
        source_branch = (form.merge_source.data or "").strip()
        target_branch = (form.merge_target.data or project.default_branch or "").strip()
        if not source_branch or not target_branch:
            flash("Source and target branches are required to merge.", "danger")
            return redirect(url_for("admin.dashboard"))
        try:
            merge_branch(project, source_branch, target_branch)
        except RuntimeError as exc:
            flash(str(exc), "danger")
        else:
            flash(f"Merged {source_branch} into {target_branch} for {project.name}.", "success")
        return redirect(url_for("admin.dashboard"))

    if form.delete_submit.data:
        branch_to_delete = (form.delete_branch.data or "").strip()
        if not branch_to_delete:
            flash("Select a branch to delete.", "danger")
            return redirect(url_for("admin.dashboard"))
        try:
            delete_project_branch(project, branch_to_delete, force=True)
        except RuntimeError as exc:
            flash(str(exc), "danger")
        else:
            flash(f"Deleted branch {branch_to_delete} for {project.name}.", "success")
        return redirect(url_for("admin.dashboard"))

    flash("Select a branch action.", "warning")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/tenants", methods=["GET", "POST"])
@admin_required
def manage_tenants():
    form = TenantForm()
    delete_form = TenantDeleteForm()
    appearance_form = TenantAppearanceForm()

    if appearance_form.save.data and appearance_form.validate_on_submit():
        tenant_id_raw = appearance_form.tenant_id.data
        try:
            tenant_id = int(tenant_id_raw)
        except (TypeError, ValueError):
            flash("Invalid tenant selection.", "warning")
            return redirect(url_for("admin.manage_tenants"))

        tenant = Tenant.query.get(tenant_id)
        if tenant is None:
            flash("Tenant not found.", "warning")
            return redirect(url_for("admin.manage_tenants"))

        tenant.color = sanitize_tenant_color(appearance_form.color.data)
        db.session.commit()
        flash(f"Updated color for tenant '{tenant.name}'.", "success")
        return redirect(url_for("admin.manage_tenants"))

    if delete_form.submit.data and delete_form.validate_on_submit():
        tenant_id_raw = delete_form.tenant_id.data
        try:
            tenant_id = int(tenant_id_raw)
        except (TypeError, ValueError):
            flash("Invalid tenant selection.", "warning")
            return redirect(url_for("admin.manage_tenants"))

        tenant = Tenant.query.get(tenant_id)
        if tenant is None:
            flash("Tenant already removed or not found.", "info")
            return redirect(url_for("admin.manage_tenants"))

        db.session.delete(tenant)
        db.session.commit()
        flash(f"Tenant '{tenant.name}' removed.", "success")
        return redirect(url_for("admin.manage_tenants"))

    if form.validate_on_submit() and not delete_form.submit.data:
        tenant = Tenant(
            name=form.name.data,
            description=form.description.data,
            color=sanitize_tenant_color(form.color.data),
        )
        db.session.add(tenant)
        db.session.commit()
        flash("Tenant created.", "success")
        return redirect(url_for("admin.manage_tenants"))

    tenants = Tenant.query.order_by(Tenant.name).all()
    tenant_rows: list[tuple[Tenant, TenantAppearanceForm]] = []
    for tenant in tenants:
        row_form = TenantAppearanceForm(formdata=None)
        row_form.tenant_id.data = tenant.id
        row_form.color.data = tenant.color or DEFAULT_TENANT_COLOR
        tenant_rows.append((tenant, row_form))

    return render_template(
        "admin/tenants.html",
        form=form,
        delete_form=delete_form,
        tenant_rows=tenant_rows,
        tenants=tenants,
    )


@admin_bp.route("/issues", methods=["GET"])
@admin_required
def manage_issues():
    issues = (
        ExternalIssue.query.options(
            selectinload(ExternalIssue.project_integration)
            .selectinload(ProjectIntegration.project)
            .selectinload(Project.tenant),
            selectinload(ExternalIssue.project_integration)
            .selectinload(ProjectIntegration.integration),
        ).all()
    )

    sorted_issues = sorted(issues, key=_issue_sort_key, reverse=True)
    tenant_counts: Counter[str] = Counter()
    tenant_labels: dict[str, str] = {}
    for issue in issues:
        tenant = None
        if issue.project_integration and issue.project_integration.project:
            tenant = issue.project_integration.project.tenant
        tenant_key = str(tenant.id) if tenant else "__unknown__"
        tenant_label = tenant.name if tenant else "Unknown tenant"
        tenant_counts[tenant_key] += 1
        tenant_labels.setdefault(tenant_key, tenant_label)

    status_counts: Counter[str] = Counter()
    status_labels: dict[str, str] = {}
    issue_entries: list[dict[str, object]] = []
    provider_statuses: dict[str, set[str]] = defaultdict(set)

    for issue in sorted_issues:
        status_key, status_label = normalize_issue_status(issue.status)
        status_counts[status_key] += 1
        status_labels.setdefault(status_key, status_label)

        integration = issue.project_integration.integration if issue.project_integration else None
        project = issue.project_integration.project if issue.project_integration else None
        tenant = project.tenant if project else None
        provider_key = (integration.provider or "").lower() if integration and integration.provider else ""

        updated_reference = issue.external_updated_at or issue.updated_at or issue.created_at

        codex_command = current_app.config["ALLOWED_AI_TOOLS"].get(
            "codex", current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
        )

        description_text = extract_issue_description(issue)

        issue_entries.append(
            {
                "id": issue.id,
                "external_id": issue.external_id,
                "title": issue.title,
                "status": issue.status,
                "status_key": status_key,
                "status_label": status_label,
                "assignee": issue.assignee,
                "url": issue.url,
                "labels": issue.labels or [],
                "provider": integration.provider if integration else "unknown",
                "provider_key": provider_key,
                "integration_name": integration.name if integration else "",
                "project_name": project.name if project else "",
                "project_id": project.id if project else None,
                "tenant_name": tenant.name if tenant else "",
                "tenant_id": tenant.id if tenant else None,
                "tenant_color": tenant.color if tenant else DEFAULT_TENANT_COLOR,
                "updated_display": _format_issue_timestamp(updated_reference),
                "updated_sort": _issue_sort_key(issue),
                "description": description_text,
                "description_available": bool(description_text),
                "description_fallback": MISSING_ISSUE_DETAILS_MESSAGE,
                "prepare_endpoint": url_for("projects.prepare_issue_context", project_id=project.id, issue_id=issue.id) if project else None,
                "codex_target": url_for("projects.project_ai_console", project_id=project.id) if project else None,
                "codex_payload": {
                    "prompt": "",
                    "command": codex_command,
                    "tool": "codex",
                    "autoStart": True,
                    "issueId": issue.id,
                    "agentPath": None,
                    "tmuxTarget": None,
                } if project else None,
                "populate_endpoint": url_for("projects.populate_issue_agents_md", project_id=project.id, issue_id=issue.id) if project else None,
                "close_endpoint": url_for("projects.close_issue", project_id=project.id, issue_id=issue.id) if project else None,
                "can_close": status_key != "closed",
                "status_update_endpoint": url_for("admin.update_issue_status", issue_id=issue.id),
                "status_choices": None,  # placeholder
            }
        )
        if issue.status:
            provider_statuses[provider_key].add(issue.status)

    provider_status_choices = {
        key: sorted(values, key=lambda item: (item.lower(), item))
        for key, values in provider_statuses.items()
    }
    for entry in issue_entries:
        choices = provider_status_choices.get(entry["provider_key"], [])
        entry["status_choices"] = choices
    total_issue_full_count = len(issue_entries)

    # Ensure we always expose an "Open" filter option so the default view can target it
    status_labels.setdefault("open", "Open")
    status_counts.setdefault("open", 0)

    raw_filter = (request.args.get("status") or "").strip().lower()
    tenant_raw_filter = (request.args.get("tenant") or "").strip()
    raw_sort = (request.args.get("sort") or "").strip().lower()
    sort_key = raw_sort if raw_sort in ISSUE_SORT_META else ISSUE_SORT_DEFAULT_KEY
    raw_direction = (request.args.get("direction") or "").strip().lower()
    if raw_direction not in {"asc", "desc"}:
        sort_direction = ISSUE_SORT_META[sort_key]["default_direction"]
    else:
        sort_direction = raw_direction

    default_filter = "open"

    if raw_filter == "all":
        status_filter = "all"
    elif raw_filter in status_labels:
        status_filter = raw_filter
    elif raw_filter == "__none__" and "__none__" in status_labels:
        status_filter = "__none__"
    else:
        status_filter = default_filter

    if tenant_raw_filter and tenant_raw_filter.lower() != "all":
        if tenant_raw_filter in tenant_labels:
            tenant_filter = tenant_raw_filter
        else:
            tenant_filter = "all"
    else:
        tenant_filter = "all"

    def _matches(entry: dict[str, object]) -> bool:
        if status_filter != "all" and entry.get("status_key") != status_filter:
            return False
        if tenant_filter != "all":
            entry_tenant = entry.get("tenant_id")
            entry_key = str(entry_tenant) if entry_tenant is not None else "__unknown__"
            return entry_key == tenant_filter
        return True

    filtered_issues = [entry for entry in issue_entries if _matches(entry)]
    total_issue_count = len(filtered_issues)

    def _string_sort_key(field: str, transform=None):
        def _key(entry: dict[str, object]):
            value = entry.get(field)
            if transform is not None:
                value = transform(value)
            text = "" if value is None else str(value)
            return (text.casefold(), text, entry.get("external_id") or "")

        return _key

    sort_key_functions = {
        "external_id": _string_sort_key("external_id"),
        "title": _string_sort_key("title"),
        "status": _string_sort_key("status_label"),
        "provider": _string_sort_key("provider"),
        "project": _string_sort_key("project_name"),
        "tenant": _string_sort_key("tenant_name"),
        "assignee": _string_sort_key("assignee"),
        "labels": _string_sort_key("labels", transform=lambda labels: ", ".join(labels or [])),
        "updated": lambda entry: entry.get("updated_sort"),
    }

    key_func = sort_key_functions.get(sort_key, sort_key_functions[ISSUE_SORT_DEFAULT_KEY])
    issues_for_template = sorted(
        filtered_issues,
        key=key_func,
        reverse=(sort_direction == "desc"),
    )

    status_options = [
        {
            "value": "all",
            "label": "All statuses",
            "count": total_issue_full_count,
        }
    ]

    def _status_option_sort_key(item: tuple[str, str]) -> tuple[int, str]:
        key, label = item
        priority = 0 if key == "open" else 1
        return priority, label.lower()

    for status_key, status_label in sorted(status_labels.items(), key=_status_option_sort_key):
        status_options.append(
            {
                "value": status_key,
                "label": status_label,
                "count": status_counts.get(status_key, 0),
            }
        )

    status_filter_label = (
        "All statuses"
        if status_filter == "all"
        else status_labels.get(status_filter, status_filter.title())
    )

    tenant_options = [
        {
            "value": "all",
            "label": "All tenants",
            "count": total_issue_full_count,
        }
    ]

    for key, label in sorted(tenant_labels.items(), key=lambda item: item[1].lower()):
        tenant_options.append(
            {
                "value": key,
                "label": label,
                "count": tenant_counts.get(key, 0),
            }
        )

    tenant_filter_label = (
        "All tenants"
        if tenant_filter == "all"
        else tenant_labels.get(tenant_filter, tenant_filter)
    )

    sort_state = {"key": sort_key, "direction": sort_direction}
    sort_columns = [dict(column) for column in ISSUE_SORT_COLUMNS]

    base_query_params: dict[str, str] = {}
    if "status" in request.args:
        base_query_params["status"] = status_filter
    if "tenant" in request.args:
        base_query_params["tenant"] = tenant_filter

    sort_headers: dict[str, dict[str, object]] = {}
    for column in sort_columns:
        column_key = column["key"]
        is_active = column_key == sort_key
        current_direction = sort_direction if is_active else None
        if is_active:
            next_direction = "asc" if sort_direction == "desc" else "desc"
        else:
            next_direction = column["default_direction"]

        query_params = {**base_query_params, "sort": column_key, "direction": next_direction}
        sort_headers[column_key] = {
            "url": url_for("admin.manage_issues", **query_params),
            "is_active": is_active,
            "current_direction": current_direction,
            "next_direction": next_direction,
            "aria_sort": (
                "ascending"
                if current_direction == "asc"
                else "descending"
                if current_direction == "desc"
                else "none"
            ),
        }

    current_view_url = request.full_path if request.query_string else request.path
    if current_view_url.endswith("?"):
        current_view_url = current_view_url[:-1]

    return render_template(
        "admin/issues.html",
        issues=issues_for_template,
        status_filter=status_filter,
        status_filter_label=status_filter_label,
        status_options=status_options,
        tenant_filter=tenant_filter,
        tenant_filter_label=tenant_filter_label,
        tenant_options=tenant_options,
        total_issue_count=total_issue_count,
        total_issue_full_count=total_issue_full_count,
        sort_columns=sort_columns,
        sort_headers=sort_headers,
        sort_state=sort_state,
        sort_key=sort_key,
        sort_direction=sort_direction,
        issue_status_max_length=ISSUE_STATUS_MAX_LENGTH,
        current_view_url=current_view_url,
    )


@admin_bp.route("/issues/<int:issue_id>/status", methods=["POST"])
@admin_required
def update_issue_status(issue_id: int):
    next_url = request.form.get("next") or url_for("admin.manage_issues")
    parsed_next = urlparse(next_url)
    if parsed_next.netloc:
        next_url = url_for("admin.manage_issues")

    try:
        issue = update_issue_status_service(issue_id, request.form.get("status"))
        db.session.commit()
    except IssueUpdateError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Failed to update issue status", extra={"issue_id": issue_id})
        flash("Unexpected error while updating issue status.", "danger")
    else:
        status_label = issue.status or "unspecified"
        flash(f"Updated status for issue {issue.external_id} to {status_label}.", "success")

    return redirect(next_url)


@admin_bp.route("/issues/refresh", methods=["POST"])
@admin_required
def refresh_all_issues():
    force_full = bool(request.form.get("force_full"))
    try:
        integrations = ProjectIntegration.query.options(
            selectinload(ProjectIntegration.integration)
        ).all()
        results = sync_tenant_integrations(integrations, force_full=force_full)
        total_updated = sum(len(issues or []) for issues in results.values())
    except IssueSyncError as exc:
        db.session.rollback()
        flash(f"Issue refresh failed: {exc}", "danger")
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Global issue refresh failed")
        flash("Unexpected error while refreshing issues.", "danger")
    else:
        if total_updated:
            flash(f"Refreshed issues across all integrations ({total_updated} updated).", "success")
        elif force_full:
            flash("Completed full issue resync with no new changes detected.", "success")
        else:
            flash("Issue caches are already up to date.", "success")

    return redirect(url_for("admin.manage_issues"))


@admin_bp.route("/projects", methods=["GET", "POST"])
@admin_required
def manage_projects():
    form = ProjectForm()
    delete_form = ProjectDeleteForm()
    form.tenant_id.choices = [(t.id, t.name) for t in Tenant.query.order_by(Tenant.name)]
    form.owner_id.choices = [(u.id, u.email) for u in User.query.order_by(User.email)]

    if not form.tenant_id.choices:
        flash("Create a tenant before adding projects.", "warning")
    if not form.owner_id.choices:
        flash("No users available to assign as project owner.", "warning")

    if delete_form.submit.data and delete_form.validate_on_submit():
        project_id_raw = delete_form.project_id.data
        try:
            project_id = int(project_id_raw)
        except (TypeError, ValueError):
            flash("Invalid project selection.", "warning")
            return redirect(url_for("admin.manage_projects"))

        project = Project.query.get(project_id)
        if project is None:
            flash("Project already removed or not found.", "info")
            return redirect(url_for("admin.manage_projects"))

        repo_path_str = project.local_path
        project_name = project.name

        db.session.delete(project)
        db.session.commit()

        if repo_path_str:
            try:
                repo_path = Path(repo_path_str).resolve()
                storage_root = Path(current_app.config["REPO_STORAGE_PATH"]).resolve()
            except (FileNotFoundError, RuntimeError, OSError, ValueError):
                repo_path = None
            else:
                if (
                    repo_path != storage_root
                    and storage_root in repo_path.parents
                    and repo_path.exists()
                ):
                    try:
                        shutil.rmtree(repo_path, ignore_errors=False)
                        current_app.logger.info(
                            "Removed repository path for deleted project %s: %s",
                            project_name,
                            repo_path,
                        )
                    except OSError as exc:
                        current_app.logger.warning(
                            "Failed to remove repository path %s: %s", repo_path, exc
                        )

        flash(f"Project '{project_name}' removed.", "success")
        return redirect(url_for("admin.manage_projects"))

    if form.validate_on_submit() and not delete_form.submit.data:
        storage_root = Path(current_app.config["REPO_STORAGE_PATH"])
        storage_root.mkdir(parents=True, exist_ok=True)
        local_path = storage_root / f"{form.name.data.lower().replace(' ', '-')}"

        project = Project(
            name=form.name.data,
            repo_url=form.repo_url.data,
            default_branch=form.default_branch.data,
            description=form.description.data,
            tenant_id=form.tenant_id.data,
            owner_id=form.owner_id.data,
            local_path=str(local_path),
        )
        db.session.add(project)
        db.session.commit()

        ensure_repo_checkout(project)
        flash("Project registered and repository cloned.", "success")
        return redirect(url_for("admin.manage_projects"))

    projects = Project.query.order_by(Project.created_at.desc()).all()
    return render_template("admin/projects.html", form=form, delete_form=delete_form, projects=projects)


@admin_bp.route("/integrations", methods=["GET", "POST"])
@admin_required
def manage_integrations():
    integration_form = TenantIntegrationForm()
    integration_delete_form = TenantIntegrationDeleteForm()
    project_form = ProjectIntegrationForm()

    tenants = Tenant.query.order_by(Tenant.name).all()
    integration_form.tenant_id.choices = [(t.id, t.name) for t in tenants]

    integrations_q = TenantIntegration.query.order_by(
        TenantIntegration.enabled.desc(), TenantIntegration.created_at.desc()
    )
    integrations_list = integrations_q.all()

    integration_choices = []
    for integration in integrations_list:
        tenant_name = integration.tenant.name if integration.tenant else "Unknown"
        label = f"{tenant_name} - {integration.name} ({integration.provider.title()})"
        integration_choices.append((integration.id, label))
    project_form.integration_id.choices = integration_choices

    project_choices = []
    for project in Project.query.order_by(Project.name).all():
        tenant_name = project.tenant.name if project.tenant else "Tenant?"
        project_choices.append((project.id, f"{tenant_name} - {project.name}"))
    project_form.project_id.choices = project_choices

    if integration_delete_form.submit.data and integration_delete_form.validate_on_submit():
        try:
            integration_id = int(integration_delete_form.integration_id.data)
        except (TypeError, ValueError):
            flash("Invalid integration selection.", "warning")
            return redirect(url_for("admin.manage_integrations"))

        integration = TenantIntegration.query.get(integration_id)
        if integration is None:
            flash("Integration already removed or not found.", "info")
            return redirect(url_for("admin.manage_integrations"))

        name_display = integration.name
        db.session.delete(integration)
        db.session.commit()
        flash(f"Integration '{name_display}' removed.", "success")
        return redirect(url_for("admin.manage_integrations"))

    if integration_form.save.data and integration_form.validate_on_submit():
        existing = TenantIntegration.query.filter_by(
            tenant_id=integration_form.tenant_id.data,
            name=integration_form.name.data.strip(),
        ).first()
        if existing:
            integration_form.name.errors.append(
                "Integration name already exists for this tenant."
            )
        else:
            provider_key = (integration_form.provider.data or "").strip().lower()
            settings: dict[str, Any] = {}
            form_valid = True
            if provider_key == "jira":
                jira_email = (integration_form.jira_email.data or "").strip()
                if not jira_email:
                    integration_form.jira_email.errors.append(
                        "Jira integrations require an account email."
                    )
                    form_valid = False
                elif "@" not in jira_email:
                    integration_form.jira_email.errors.append("Enter a valid email address.")
                    form_valid = False
                else:
                    settings["username"] = jira_email

            if not form_valid:
                pass
            else:
                integration = TenantIntegration(
                    tenant_id=integration_form.tenant_id.data,
                    name=integration_form.name.data.strip(),
                    provider=integration_form.provider.data,
                    base_url=(integration_form.base_url.data or "").strip() or None,
                    api_token=(integration_form.api_token.data or "").strip(),
                    enabled=integration_form.enabled.data,
                    settings=settings,
                )
                db.session.add(integration)
                db.session.commit()
                flash("Integration saved.", "success")
                return redirect(url_for("admin.manage_integrations"))

    elif project_form.link.data and project_form.validate_on_submit():
        integration = TenantIntegration.query.get(project_form.integration_id.data)
        project = Project.query.get(project_form.project_id.data)
        valid = True
        if integration is None:
            project_form.integration_id.errors.append("Selected integration not found.")
            valid = False
        if project is None:
            project_form.project_id.errors.append("Selected project not found.")
            valid = False

        if valid and integration and project and integration.tenant_id != project.tenant_id:
            project_form.integration_id.errors.append(
                "Integration tenant does not match the selected project."
            )
            valid = False

        if valid and integration and project:
            existing_link = ProjectIntegration.query.filter_by(
                integration_id=integration.id,
                project_id=project.id,
            ).first()
            if existing_link:
                project_form.external_identifier.errors.append(
                    "This project is already linked to the selected integration."
                )
                valid = False

        if valid and integration and project:
            config: dict[str, str] = {}
            jira_jql = (project_form.jira_jql.data or "").strip()
            if jira_jql and integration.provider.lower() == "jira":
                config["jql"] = jira_jql
            project_integration = ProjectIntegration(
                project_id=project.id,
                integration_id=integration.id,
                external_identifier=project_form.external_identifier.data.strip(),
                config=config,
            )
            db.session.add(project_integration)
            db.session.commit()
            flash("Project integration linked.", "success")
            return redirect(url_for("admin.manage_integrations"))

    integration_load_options = [
        selectinload(TenantIntegration.tenant),
        selectinload(TenantIntegration.project_integrations).selectinload(
            ProjectIntegration.project
        ),
        selectinload(TenantIntegration.project_integrations).selectinload(
            ProjectIntegration.issues
        ),
    ]
    integrations = (
        TenantIntegration.query.options(*integration_load_options)
        .order_by(TenantIntegration.enabled.desc(), TenantIntegration.created_at.desc())
        .all()
    )

    update_forms: dict[int, ProjectIntegrationUpdateForm] = {}
    delete_forms: dict[int, ProjectIntegrationDeleteForm] = {}
    for integration in integrations:
        for link in integration.project_integrations:
            update_form = ProjectIntegrationUpdateForm(prefix=f"update-{link.id}")
            update_form.external_identifier.data = link.external_identifier
            if integration.provider.lower() == "jira":
                update_form.jira_jql.data = (link.config or {}).get("jql", "")
            delete_form = ProjectIntegrationDeleteForm(prefix=f"delete-{link.id}")
            update_forms[link.id] = update_form
            delete_forms[link.id] = delete_form

    return render_template(
        "admin/integrations.html",
        integration_form=integration_form,
        integration_delete_form=integration_delete_form,
        project_form=project_form,
        integrations=integrations,
        integration_update_forms=update_forms,
        integration_delete_forms=delete_forms,
    )


@admin_bp.route("/integrations/test", methods=["POST"])
@admin_required
def test_integration() -> Any:
    payload = request.get_json(silent=True) or {}
    provider = (payload.get("provider") or "").strip().lower()
    api_token = (payload.get("api_token") or "").strip()
    base_url = (payload.get("base_url") or "").strip() or None
    jira_email = (payload.get("jira_email") or "").strip()
    username = jira_email if provider == "jira" else None

    if not provider or not api_token:
        return jsonify({"ok": False, "message": "Provider and API token are required."}), 400

    if provider == "jira" and (not base_url or not username):
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Jira integrations require a base URL and account email.",
                }
            ),
            400,
        )

    try:
        message = test_integration_connection(provider, api_token, base_url, username=username)
    except IssueSyncError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    return jsonify({"ok": True, "message": message})


@admin_bp.route("/integrations/project/<int:project_integration_id>/update", methods=["POST"])
@admin_required
def update_project_integration(project_integration_id: int):
    link = ProjectIntegration.query.options(
        selectinload(ProjectIntegration.integration).selectinload(TenantIntegration.tenant),
        selectinload(ProjectIntegration.project),
    ).get_or_404(project_integration_id)

    prefix = f"update-{project_integration_id}"
    form = ProjectIntegrationUpdateForm(prefix=prefix)
    prefixed_field = f"{prefix}-external_identifier"
    if prefixed_field not in request.form and "external_identifier" in request.form:
        form = ProjectIntegrationUpdateForm()
    if not form.validate_on_submit():
        flash("Unable to update project integration. Please fix the form errors.", "danger")
        return redirect(url_for("admin.manage_integrations"))

    external_identifier = (form.external_identifier.data or "").strip()
    if not external_identifier:
        flash("External identifier cannot be empty.", "danger")
        return redirect(url_for("admin.manage_integrations"))

    link.external_identifier = external_identifier
    config = dict(link.config or {})
    provider = (link.integration.provider if link.integration else "").lower()
    if provider == "jira":
        jira_jql = (form.jira_jql.data or "").strip()
        if jira_jql:
            config["jql"] = jira_jql
        else:
            config.pop("jql", None)
    else:
        config.pop("jql", None)
    link.config = config
    db.session.commit()

    flash("Project integration updated.", "success")
    return redirect(url_for("admin.manage_integrations"))


@admin_bp.route("/integrations/project/<int:project_integration_id>/delete", methods=["POST"])
@admin_required
def delete_project_integration(project_integration_id: int):
    link = ProjectIntegration.query.get_or_404(project_integration_id)
    form = ProjectIntegrationDeleteForm(prefix=f"delete-{project_integration_id}")
    if not form.validate_on_submit():
        flash("Unable to remove project integration.", "danger")
        return redirect(url_for("admin.manage_integrations"))

    db.session.delete(link)
    db.session.commit()
    flash("Project integration removed.", "success")
    return redirect(url_for("admin.manage_integrations"))


@admin_bp.route("/ssh-keys", methods=["GET", "POST"])
@admin_required
def manage_ssh_keys():
    form = SSHKeyForm()
    delete_form = SSHKeyDeleteForm()
    tenant_choices = [(0, "Unassigned")] + [
        (t.id, t.name) for t in Tenant.query.order_by(Tenant.name)
    ]
    form.tenant_id.choices = tenant_choices

    if form.validate_on_submit():
        public_key = (form.public_key.data or "").strip()
        private_key_raw = (form.private_key.data or "").strip()
        try:
            fingerprint = compute_fingerprint(public_key)
        except ValueError as exc:  # noqa: BLE001
            form.public_key.errors.append(str(exc))
        else:
            existing = SSHKey.query.filter_by(fingerprint=fingerprint).first()
            if existing:
                form.public_key.errors.append(
                    "Fingerprint already registered under another key."
                )
            else:
                ssh_key = SSHKey(
                    name=form.name.data,
                    public_key=public_key,
                    fingerprint=fingerprint,
                    user_id=current_user.model.id,
                    tenant_id=form.tenant_id.data or None,
                )
                db.session.add(ssh_key)
                try:
                    db.session.flush()
                    if private_key_raw:
                        _store_private_key_file(ssh_key, private_key_raw)
                    db.session.commit()
                except OSError as exc:
                    db.session.rollback()
                    current_app.logger.error("Failed to save SSH private key: %s", exc)
                    form.private_key.errors.append("Failed to store private key on disk.")
                else:
                    flash("SSH key added.", "success")
                    return redirect(url_for("admin.manage_ssh_keys"))

    keys = (
        SSHKey.query.filter_by(user_id=current_user.model.id)
        .order_by(SSHKey.created_at.desc())
        .all()
    )
    return render_template("admin/ssh_keys.html", form=form, delete_form=delete_form, ssh_keys=keys)


@admin_bp.route("/ssh-keys/<int:key_id>", methods=["GET", "POST"])
@admin_required
def edit_ssh_key(key_id: int):
    ssh_key = SSHKey.query.get_or_404(key_id)

    tenant_choices = [(0, "Unassigned")] + [
        (t.id, t.name) for t in Tenant.query.order_by(Tenant.name)
    ]
    form = SSHKeyForm(obj=ssh_key)
    form.tenant_id.choices = tenant_choices
    form.tenant_id.data = ssh_key.tenant_id or 0
    if request.method == "GET":
        form.private_key.data = ""
        form.remove_private_key.data = False

    if form.validate_on_submit():
        public_key = (form.public_key.data or "").strip()
        private_key_raw = (form.private_key.data or "").strip()
        remove_private = bool(form.remove_private_key.data)
        try:
            fingerprint = compute_fingerprint(public_key)
        except ValueError as exc:  # noqa: BLE001
            form.public_key.errors.append(str(exc))
        else:
            existing = (
                SSHKey.query.filter(SSHKey.fingerprint == fingerprint, SSHKey.id != ssh_key.id)
                .first()
            )
            if existing:
                form.public_key.errors.append(
                    "Another key with this fingerprint already exists."
                )
            else:
                ssh_key.name = form.name.data
                ssh_key.public_key = public_key
                ssh_key.fingerprint = fingerprint
                ssh_key.tenant_id = form.tenant_id.data or None
                try:
                    db.session.flush()
                    if private_key_raw:
                        _store_private_key_file(ssh_key, private_key_raw)
                    elif remove_private and ssh_key.private_key_path:
                        _remove_private_key_file(ssh_key)
                    db.session.commit()
                except OSError as exc:
                    db.session.rollback()
                    current_app.logger.error("Failed to update SSH private key: %s", exc)
                    if private_key_raw:
                        form.private_key.errors.append("Failed to store private key on disk.")
                    else:
                        flash("Unable to update private key material.", "danger")
                else:
                    flash("SSH key updated.", "success")
                    return redirect(url_for("admin.manage_ssh_keys"))

    private_key_contents = None
    if ssh_key.private_key_path:
        try:
            resolved_path = resolve_private_key_path(ssh_key.private_key_path)
            if resolved_path:
                private_key_contents = resolved_path.read_text().strip()
        except (OSError, UnicodeDecodeError):
            private_key_contents = "(unable to read private key file)"

    return render_template(
        "admin/ssh_key_edit.html",
        form=form,
        ssh_key=ssh_key,
        private_key_contents=private_key_contents,
    )


@admin_bp.route("/ssh-keys/<int:key_id>/delete", methods=["POST"])
@admin_required
def delete_ssh_key(key_id: int):
    form = SSHKeyDeleteForm()
    if not form.validate_on_submit():
        flash("Unable to remove SSH key.", "danger")
        return redirect(url_for("admin.manage_ssh_keys"))
    try:
        submitted_id = int(form.key_id.data)
    except (TypeError, ValueError):
        flash("Invalid SSH key selection.", "warning")
        return redirect(url_for("admin.manage_ssh_keys"))
    if submitted_id != key_id:
        flash("Mismatched SSH key identifier.", "warning")
        return redirect(url_for("admin.manage_ssh_keys"))

    ssh_key = SSHKey.query.get_or_404(key_id)
    if ssh_key.user_id != current_user.model.id:
        flash("You do not own this SSH key.", "danger")
        return redirect(url_for("admin.manage_ssh_keys"))

    _remove_private_key_file(ssh_key)

    db.session.delete(ssh_key)
    db.session.commit()
    flash("SSH key removed.", "success")
    return redirect(url_for("admin.manage_ssh_keys"))
