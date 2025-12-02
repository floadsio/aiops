from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, cast
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required  # type: ignore
from markupsafe import Markup, escape
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..constants import DEFAULT_TENANT_COLOR, sanitize_tenant_color
from ..extensions import db
from ..forms.admin import (
    AIToolUpdateForm,
    APIKeyCreateForm,
    APIKeyRevokeForm,
    BackupCreateForm,
    BackupDeleteForm,
    BackupRestoreForm,
    CreateUserForm,
    IssueDashboardCreateForm,
    LinuxUserMappingForm,
    MigrationRunForm,
    PermissionsCheckForm,
    PermissionsFixForm,
    ProjectBranchForm,
    ProjectDeleteForm,
    ProjectForm,
    ProjectGitRefreshForm,
    ProjectIntegrationDeleteForm,
    ProjectIntegrationForm,
    ProjectIntegrationUpdateForm,
    ProjectIssueSyncForm,
    QuickBranchSwitchForm,
    SSHKeyDeleteForm,
    SSHKeyForm,
    TenantAppearanceForm,
    TenantDeleteForm,
    TenantForm,
    TenantIntegrationDeleteForm,
    TenantIntegrationForm,
    TenantIntegrationUpdateForm,
    TmuxResyncForm,
    UpdateApplicationForm,
    UserCredentialCreateForm,
    UserCredentialDeleteForm,
    UserDeleteForm,
    UserIdentityMapDeleteForm,
    UserIdentityMapForm,
    UserResetPasswordForm,
    UserToggleAdminForm,
    UserUpdateForm,
)
from ..models import (
    APIKey,
    ExternalIssue,
    Project,
    ProjectIntegration,
    SSHKey,
    Tenant,
    TenantIntegration,
    User,
    UserIdentityMap,
)
from ..security import hash_password
from ..services.agent_context import (
    MISSING_ISSUE_DETAILS_MESSAGE,
    extract_issue_description,
    extract_issue_description_html,
)
from ..services.ai_cli_update_service import (
    CLICommandError,
    run_ai_tool_update,
)
from ..services.backup_service import (
    BackupError,
    create_backup,
    get_backup,
    list_backups,
    restore_backup,
)
from ..services.branch_state import (
    BranchSwitchError,
    configure_branch_form,
    current_repo_branch,
    remember_branch,
    switch_repo_branch,
)
from ..services.git_service import (
    checkout_or_create_branch,
    delete_project_branch,
    ensure_repo_checkout,
    get_repo_status,
    list_project_branches,
    merge_branch,
    run_git_action,
)
from ..services.issues import (
    CREATE_PROVIDER_REGISTRY,
    ISSUE_STATUS_MAX_LENGTH,
    create_issue_for_project_integration,
    IssueSyncError,
    IssueUpdateError,
    sync_project_integration,
    sync_tenant_integrations,
    test_integration_connection,
)
from ..services.issues import (
    update_issue_status as update_issue_status_service,
)
from ..services.issues.utils import normalize_issue_status
from ..services.key_service import (
    compute_fingerprint,
    format_private_key_path,
    resolve_private_key_path,
)
from ..services.log_service import LogReadError, read_log_tail
from ..services.migration_service import MigrationError, run_db_upgrade
from ..services.permissions_service import (
    PermissionsError,
    check_permissions,
    fix_permissions,
)
from ..services.tmux_metadata import get_tmux_ssh_keys, get_tmux_tool, prune_tmux_tools
from ..services.tmux_service import (
    TmuxServiceError,
    list_windows_for_aliases,
    session_name_for_user,
    sync_project_windows,
)
from ..services.update_service import UpdateError, run_update_script
from ..services.workspace_service import get_workspace_path

ChoiceItem = tuple[Any, str] | tuple[Any, str, dict[str, Any]]
ChoiceList = list[ChoiceItem]

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


def _custom_field_input_name(field_key: str) -> str:
    safe = "".join(
        ch if ch.isalnum() or ch in {"_", "-", "."} else "_"
        for ch in field_key
    )
    return f"custom_field__{safe}"


def _normalize_custom_fields(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not config:
        return entries
    raw_fields = config.get("custom_fields")
    if not isinstance(raw_fields, list):
        return entries
    for raw in raw_fields:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or raw.get("id") or "").strip()
        if not key:
            continue
        label = str(raw.get("label") or key)
        field_type = str(raw.get("type") or "text").lower()
        if field_type not in {"text", "number", "select"}:
            field_type = "text"
        normalized_options: list[dict[str, str]] = []
        options = raw.get("options")
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict):
                    value = option.get("value")
                    label_text = option.get("label") or value
                else:
                    value = option
                    label_text = option
                if value is None:
                    continue
                normalized_options.append(
                    {"value": str(value), "label": str(label_text)}
                )
        entries.append(
            {
                "key": key,
                "label": label,
                "type": field_type,
                "required": bool(raw.get("required")),
                "description": raw.get("description"),
                "options": normalized_options,
                "input_name": _custom_field_input_name(key),
            }
        )
    return entries


def _build_issue_creation_targets() -> tuple[
    dict[int, ProjectIntegration], list[tuple[int, str]], list[dict[str, Any]]
]:
    query = (
        ProjectIntegration.query.options(
            selectinload(ProjectIntegration.project).selectinload(Project.tenant),
            selectinload(ProjectIntegration.integration),
        )
        .join(ProjectIntegration.integration)
        .filter(TenantIntegration.enabled.is_(True))
    )
    link_by_id: dict[int, ProjectIntegration] = {}
    choices: list[tuple[int, str]] = []
    metadata: list[dict[str, Any]] = []
    for link in query.all():
        integration = link.integration
        project = link.project
        if integration is None or project is None:
            continue
        provider_key = (integration.provider or "").lower()
        if provider_key not in CREATE_PROVIDER_REGISTRY:
            continue
        tenant = project.tenant
        tenant_label = tenant.name if tenant else "Unknown tenant"
        provider_label = integration.name or integration.provider or "Integration"
        display_label = f"{tenant_label} → {project.name} ({provider_label})"
        link_by_id[link.id] = link
        choices.append((link.id, display_label))
        config = link.config or {}
        custom_fields = _normalize_custom_fields(config)
        metadata.append(
            {
                "id": link.id,
                "provider": provider_key,
                "provider_label": provider_label,
                "project_name": project.name,
                "tenant_name": tenant_label,
                "issue_type_default": config.get("issue_type"),
                "custom_fields": custom_fields,
                "supports": {
                    "milestone": provider_key in {"github", "gitlab"},
                    "priority": provider_key == "jira",
                    "issue_type": provider_key == "jira",
                    "custom_fields": bool(custom_fields),
                },
            }
        )
    choices.sort(key=lambda entry: entry[1].lower())
    metadata.sort(key=lambda entry: entry["project_name"].lower())
    return link_by_id, choices, metadata


def _build_assignee_choices() -> tuple[
    list[tuple[int, str]], dict[int, UserIdentityMap], dict[int, dict[str, bool]]
]:
    users = User.query.order_by(User.name).all()
    user_ids = [user.id for user in users]
    identity_map: dict[int, UserIdentityMap] = {}
    if user_ids:
        for entry in UserIdentityMap.query.filter(
            UserIdentityMap.user_id.in_(user_ids)
        ).all():
            identity_map[entry.user_id] = entry
    choices: list[tuple[int, str]] = [(0, "— No Assignee —")]
    capability: dict[int, dict[str, bool]] = {}
    for user in users:
        label = f"{user.name} ({user.email})"
        choices.append((user.id, label))
        identity = identity_map.get(user.id)
        capability[user.id] = {
            "github": bool(identity and identity.github_username),
            "gitlab": bool(identity and identity.gitlab_username),
            "jira": bool(identity and identity.jira_account_id),
        }
    return choices, identity_map, capability


def _extract_custom_field_values(
    field_defs: list[dict[str, Any]], form_data: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for field in field_defs:
        input_name = field.get("input_name")
        key = field.get("key")
        if not input_name or not key:
            continue
        raw_value = form_data.get(input_name, "")
        text_value = str(raw_value).strip()
        if not text_value:
            if field.get("required"):
                errors[input_name] = "This field is required."
            continue
        field_type = field.get("type", "text")
        if field_type == "number":
            try:
                if "." in text_value:
                    processed: Any = float(text_value)
                else:
                    processed = int(text_value)
            except ValueError:
                errors[input_name] = "Enter a valid number."
                continue
            values[key] = processed
        elif field_type == "select":
            options = field.get("options") or []
            allowed = {option.get("value") for option in options if option.get("value")}
            if text_value not in allowed:
                errors[input_name] = "Select a valid option."
                continue
            values[key] = text_value
        else:
            values[key] = text_value
    return values, errors


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
        resolve_private_key_path(ssh_key.private_key_path)
        if ssh_key.private_key_path
        else None
    )
    if existing_path and existing_path.exists() and existing_path != destination:
        try:
            existing_path.unlink()
        except OSError:
            current_app.logger.warning(
                "Unable to remove previous private key file %s", existing_path
            )

    if destination.exists():
        try:
            destination.unlink()
        except OSError:
            current_app.logger.warning(
                "Unable to remove existing private key file %s", destination
            )

    try:
        with destination.open("w", encoding="utf-8") as handle:
            handle.write(sanitized)
            if not sanitized.endswith("\n"):
                handle.write("\n")
        os.chmod(destination, 0o600)
    except OSError as exc:
        current_app.logger.error(
            "Failed to store private key for %s: %s", ssh_key.name, exc
        )
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


def _prepare_comment_entries(raw_comments: list[dict[str, Any]] | None):
    entries: list[dict[str, Any]] = []
    if not raw_comments:
        return entries
    for comment in raw_comments:
        if not isinstance(comment, dict):
            continue
        created_display = None
        created_value = _coerce_timestamp(comment.get("created_at"))
        if created_value:
            created_display = _format_issue_timestamp(created_value)
        entries.append(
            {
                "author": comment.get("author"),
                "body": comment.get("body") or "",
                "body_html": comment.get("body_html"),  # Pre-rendered HTML from Jira
                "created_display": created_display,
                "url": comment.get("url"),
            }
        )
    return entries


def _current_tmux_session_name() -> str:
    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    return session_name_for_user(user_obj)


def _current_user_obj():
    """Get the current user object for workspace operations."""
    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    return user_obj


def _current_linux_username() -> str | None:
    """Get the Linux username for the current user."""
    from ..services.linux_users import resolve_linux_username

    user_obj = _current_user_obj()
    if user_obj is None:
        return None
    return resolve_linux_username(user_obj)


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

    tenant_filter_raw = (request.args.get("tenant") or "").strip()
    tenant_filter_active = bool(
        tenant_filter_raw and tenant_filter_raw.lower() != "all"
    )
    tenant_filter_label: str | None = None
    tenant_filter_id: int | None = None
    if tenant_filter_active:
        try:
            tenant_filter_id = int(tenant_filter_raw)
        except ValueError:
            tenant_filter_id = None
        if tenant_filter_id is not None:
            tenant_obj = Tenant.query.get(tenant_filter_id)
            if tenant_obj:
                tenant_filter_label = tenant_obj.name
        if tenant_filter_label is None:
            tenant_filter_label = "Selected tenant"

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
        selectinload(Project.issue_integrations).selectinload(
            ProjectIntegration.integration
        ),
        selectinload(Project.issue_integrations).selectinload(
            ProjectIntegration.issues
        ),
    )
    if tenant_filter_id is not None:
        project_query = project_query.filter(Project.tenant_id == tenant_filter_id)
    project_limit_default = current_app.config.get("DASHBOARD_PROJECT_LIMIT", 10)
    project_limit_search = current_app.config.get("DASHBOARD_SEARCH_PROJECT_LIMIT", 25)
    project_limit = project_limit_search if search_query else project_limit_default
    projects = (
        project_query.order_by(Project.created_at.desc()).limit(project_limit).all()
    )
    project_cards: list[dict[str, Any]] = []
    tracked_tmux_targets: set[str] = set()
    recent_tmux_windows: list[dict[str, Any]] = []
    recent_tmux_error: str | None = None
    window_project_map: dict[str, dict[str, Any]] = {}
    tmux_session_name = _current_tmux_session_name()
    linux_username = _current_linux_username()

    # Initialize windows_by_session at the top level so it's always available
    from collections import defaultdict
    windows_by_session = defaultdict(list)

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
        status = get_repo_status(project, user=_current_user_obj())
        last_activity = _coerce_timestamp(
            getattr(project, "updated_at", None)
        ) or _coerce_timestamp(getattr(project, "created_at", None))
        status_last_commit = _coerce_timestamp(status.get("last_commit_timestamp"))
        if status_last_commit and (
            last_activity is None or status_last_commit > last_activity
        ):
            last_activity = status_last_commit
        status_last_pull = _coerce_timestamp(status.get("last_pull"))
        if status_last_pull and (
            last_activity is None or status_last_pull > last_activity
        ):
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
            tenant_color = (
                tenant.color if tenant and tenant.color else DEFAULT_TENANT_COLOR
            )
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
                window_created = _coerce_timestamp(window.created)
                if window_created and (
                    last_activity is None or window_created > last_activity
                ):
                    last_activity = window_created
                tool_label = get_tmux_tool(window.target)

                # Check if pane is dead
                from ..services.tmux_service import is_pane_dead
                pane_is_dead = is_pane_dead(window.target, linux_username=linux_username)

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
                        "tool": tool_label,
                        "ssh_keys": get_tmux_ssh_keys(window.target),
                        "pane_dead": pane_is_dead,
                    }
                )
                if window.target:
                    tracked_tmux_targets.add(window.target)

                workspace_path = get_workspace_path(project, _current_user_obj())
                window_project_map.setdefault(
                    window.target,
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "tenant_name": tenant_name,
                        "tenant_color": tenant_color,
                        "workspace_path": str(workspace_path)
                        if workspace_path
                        else None,
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
                (integration.provider or "Unknown").title()
                if integration
                else "Unknown",
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
            if integration_last_synced and (
                last_activity is None or integration_last_synced > last_activity
            ):
                last_activity = integration_last_synced

            integration_summaries.append(
                {
                    "integration_name": integration.name
                    if integration
                    else "Unknown integration",
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

        matches_query = (
            _project_matches_query(project, tmux_windows) if search_query else True
        )
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
                "last_activity": last_activity
                or datetime.min.replace(tzinfo=timezone.utc),
            }
        )
    project_cards.sort(
        key=lambda card: card.get("last_activity")
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    try:
        from ..services.ai_session_service import get_user_sessions, get_session_summary

        # Get sessions from database based on scope
        user_obj = _current_user_obj()
        current_user_id = user_obj.id if user_obj else None
        is_admin = getattr(current_user, "is_admin", False)

        if tmux_scope_show_all and is_admin:
            # Admin viewing all users' sessions
            sessions = get_user_sessions(user_id=None, active_only=True)
        else:
            # User viewing their own sessions
            sessions = get_user_sessions(user_id=current_user_id, active_only=True)

    except Exception as exc:
        import traceback
        recent_tmux_error = f"Failed to load sessions: {str(exc)}"
        current_app.logger.error(
            "Error loading AI sessions: %s\n%s", exc, traceback.format_exc()
        )
        sessions = []

    # Process sessions and group by user/session (outside try block)
    all_sessions = []
    for session in sessions:
        if not session.tmux_target:
            continue

        try:
            # Get session summary (includes tool name, etc)
            summary = get_session_summary(session)

            # Extract window name from tmux_target (format: "user:session:window" or "session:window")
            tmux_target = session.tmux_target
            target_parts = tmux_target.split(":")

            # Determine session name and window name
            if len(target_parts) >= 2:
                # Could be "user:session" or "user:session:window" or just "session:window"
                if "@" in target_parts[0] or len(target_parts) > 2:
                    # Format: "user:session" or "user:session:window"
                    session_name = target_parts[1] if len(target_parts) >= 2 else target_parts[0]
                    window_name = target_parts[2] if len(target_parts) > 2 else target_parts[1]
                else:
                    # Format: "session:window"
                    session_name = target_parts[0]
                    window_name = target_parts[1]
            else:
                # Just session name
                session_name = target_parts[0]
                window_name = "default"

            # Skip zsh windows
            if window_name.lower() == "zsh":
                continue

            # Check if pane is dead (with error handling)
            from ..services.tmux_service import is_pane_dead
            try:
                pane_is_dead = is_pane_dead(tmux_target, linux_username=linux_username)
            except Exception:
                pane_is_dead = False  # Default to not dead if we can't check

            created_display = (
                session.started_at.astimezone().strftime("%b %d, %Y • %H:%M %Z")
                if session.started_at
                else None
            )

            # Get project info if session has a project
            project_info = None
            if session.project:
                tenant = session.project.tenant
                tenant_name = tenant.name if tenant else "Unassigned"
                tenant_color = tenant.color if tenant and tenant.color else DEFAULT_TENANT_COLOR
                workspace_path = None
                try:
                    wp = get_workspace_path(session.project, _current_user_obj())
                    if wp:
                        workspace_path = str(wp)
                except Exception:
                    workspace_path = None

                project_info = {
                    "project_id": session.project.id,
                    "project_name": session.project.name,
                    "tenant_name": tenant_name,
                    "tenant_color": tenant_color,
                    "workspace_path": workspace_path,
                }

            # Get user who started the session
            owner_name = None
            if session.user:
                owner_name = (
                    session.user.name
                    or session.user.username
                    or session.user.email
                    or f"User #{session.user.id}"
                )

            # Get tool and ssh keys (with error handling)
            try:
                tool_label = session.tool or get_tmux_tool(tmux_target)
            except Exception:
                tool_label = session.tool or "unknown"

            try:
                ssh_keys = get_tmux_ssh_keys(tmux_target)
            except Exception:
                ssh_keys = []

            window_entry = {
                "session": session_name,
                "window": window_name,
                "target": tmux_target,
                "panes": 1,  # AI sessions typically use 1 pane
                "created": session.started_at,
                "created_display": created_display,
                "tool": tool_label,
                "ssh_keys": ssh_keys,
                "project": project_info,
                "pane_dead": pane_is_dead,
                "owner": owner_name,
            }

            all_sessions.append(window_entry)
            windows_by_session[session_name].append(window_entry)
            recent_tmux_windows.append(window_entry)

            if tmux_target:
                tracked_tmux_targets.add(tmux_target)
        except Exception as exc:
            current_app.logger.warning(
                "Failed to process session %s: %s",
                getattr(session, 'id', 'unknown'),
                str(exc)
            )
            continue  # Skip this session and continue with the next

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

        recent_tmux_windows = [
            entry for entry in recent_tmux_windows if _recent_tmux_matches(entry)
        ]

    pending_tasks = sum(p for p in [0])  # placeholder for task count
    prune_tmux_tools(tracked_tmux_targets)

    from ..models import PinnedIssue, PinnedComment

    pinned_issues = (
        PinnedIssue.query.filter_by(user_id=_current_user_obj().id)
        .join(ExternalIssue)
        .join(ProjectIntegration)
        .options(
            selectinload(PinnedIssue.issue)
            .selectinload(ExternalIssue.project_integration)
            .selectinload(ProjectIntegration.project)
            .selectinload(Project.tenant)
        )
        .order_by(PinnedIssue.pinned_at.desc())
        .limit(10)
        .all()
    )

    # Group pinned issues by tenant
    from collections import defaultdict
    pinned_by_tenant = defaultdict(list)
    for pinned in pinned_issues:
        tenant = pinned.issue.project_integration.project.tenant
        tenant_name = tenant.name if tenant else "No Tenant"
        pinned_by_tenant[tenant_name].append(pinned)

    # Convert to sorted list of (tenant_name, issues) tuples
    pinned_issues_grouped = sorted(pinned_by_tenant.items())

    # Load pinned comments for dashboard
    pinned_comments_raw = (
        PinnedComment.query.filter_by(user_id=_current_user_obj().id)
        .join(ExternalIssue)
        .options(
            selectinload(PinnedComment.issue)
            .selectinload(ExternalIssue.project_integration)
            .selectinload(ProjectIntegration.project)
        )
        .order_by(PinnedComment.pinned_at.desc())
        .limit(10)
        .all()
    )

    # Enrich pinned comments with actual comment data
    pinned_comments = []
    for pinned in pinned_comments_raw:
        issue = pinned.issue
        comment_data = None
        for c in (issue.comments or []):
            if str(c.get("id")) == str(pinned.comment_id):
                comment_data = c
                break
        project = issue.project_integration.project if issue.project_integration else None
        pinned_comments.append({
            "id": pinned.id,
            "issue_id": pinned.issue_id,
            "comment_id": pinned.comment_id,
            "pinned_at": pinned.pinned_at,
            "note": pinned.note,
            "issue": issue,
            "project": project,
            "comment": comment_data,
        })

    return render_template(
        "admin/dashboard.html",
        tenants=tenants,
        projects=projects,
        project_cards=project_cards,
        pending_tasks=pending_tasks,
        recent_tmux_windows=recent_tmux_windows,
        recent_tmux_error=recent_tmux_error,
        windows_by_session=windows_by_session,
        update_form=update_form,
        dashboard_query=search_query,
        tmux_scope_show_all=tmux_scope_show_all,
        tmux_scope_label=tmux_scope_label,
        tmux_scope_toggle_url=tmux_scope_toggle_url,
        tmux_scope_toggle_label=tmux_scope_toggle_label,
        dashboard_search_endpoint=dashboard_search_endpoint,
        tenant_filter_active=tenant_filter_active,
        tenant_filter_label=tenant_filter_label,
        tenant_filter_value=tenant_filter_raw,
        pinned_issues=pinned_issues,
        pinned_issues_grouped=pinned_issues_grouped,
        pinned_comments=pinned_comments,
    )


def _build_ai_tool_cards() -> list[dict[str, Any]]:
    config = current_app.config
    manage_url = url_for("admin.manage_settings")

    def _make_action(source: str, *, label: str, helper: str, command: str | None):
        command_text = (command or "").strip()
        if not command_text:
            return None
        form = AIToolUpdateForm(formdata=None)
        form.next.data = manage_url
        form.source.data = source
        return {
            "source": source,
            "label": label,
            "helper": helper,
            "command": command_text,
            "form": form,
        }

    cards: list[dict[str, Any]] = []

    codex_actions = [
        _make_action(
            "npm",
            label="Update via npm",
            helper="Runs CODEX_UPDATE_COMMAND (override in .env).",
            command=config.get("CODEX_UPDATE_COMMAND"),
        ),
    ]
    codex_brew_package = (config.get("CODEX_BREW_PACKAGE") or "").strip()
    codex_actions.append(
        _make_action(
            "brew",
            label="Update via Homebrew",
            helper="Runs brew upgrade for CODEX_BREW_PACKAGE.",
            command=f"brew upgrade {codex_brew_package}" if codex_brew_package else "",
        )
    )
    codex_actions = [action for action in codex_actions if action]
    if codex_actions:
        cards.append(
            {
                "key": "codex",
                "title": "💻 Codex CLI",
                "description": "Install or upgrade the Codex CLI without shell access.",
                "actions": codex_actions,
                "versions": None,  # Load versions on-demand for better page performance
            }
        )

    claude_actions = [
        _make_action(
            "npm",
            label="Update via npm",
            helper="Runs CLAUDE_UPDATE_COMMAND.",
            command=config.get("CLAUDE_UPDATE_COMMAND"),
        ),
    ]
    claude_brew_package = (config.get("CLAUDE_BREW_PACKAGE") or "").strip()
    claude_actions.append(
        _make_action(
            "brew",
            label="Update via Homebrew",
            helper="Runs brew upgrade for CLAUDE_BREW_PACKAGE.",
            command=f"brew upgrade {claude_brew_package}"
            if claude_brew_package
            else "",
        )
    )
    claude_actions = [action for action in claude_actions if action]
    if claude_actions:
        cards.append(
            {
                "key": "claude",
                "title": "🤖 Claude CLI",
                "description": "Keep the Claude CLI current for tmux and browser sessions.",
                "actions": claude_actions,
                "versions": None,  # Load versions on-demand for better page performance
            }
        )

    return cards


@admin_bp.route("/cleanup-closed-pinned", methods=["POST"])
@login_required
def cleanup_closed_pinned():
    """Remove all closed pinned issues for the current user."""
    from ..models import PinnedIssue, ExternalIssue

    # Find all closed pinned issues for current user
    closed_pinned = (
        db.session.query(PinnedIssue)
        .join(ExternalIssue)
        .filter(
            PinnedIssue.user_id == current_user.model.id,
            ExternalIssue.status == "closed",
        )
        .all()
    )

    count = len(closed_pinned)
    for pinned in closed_pinned:
        db.session.delete(pinned)

    db.session.commit()

    if count > 0:
        flash(
            f"Cleaned up {count} closed pinned issue{'s' if count != 1 else ''}.",
            "success",
        )
    else:
        flash("No closed pinned issues to clean up.", "info")

    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def manage_settings():
    update_form = UpdateApplicationForm()
    update_form.next.data = url_for("admin.manage_settings")
    current_branch = current_repo_branch()
    configure_branch_form(update_form, current_branch=current_branch)

    migration_form = MigrationRunForm()
    migration_form.next.data = url_for("admin.manage_settings")

    tmux_resync_form = TmuxResyncForm()
    tmux_resync_form.next.data = url_for("admin.manage_settings")

    permissions_check_form = PermissionsCheckForm()
    permissions_check_form.next.data = url_for("admin.manage_settings")

    permissions_fix_form = PermissionsFixForm()
    permissions_fix_form.next.data = url_for("admin.manage_settings")

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
                flash(
                    "Unable to create user. Please correct the errors below.", "danger"
                )
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
                    create_user_form.email.errors.append(
                        "A user with this email already exists."
                    )
                    flash(
                        "Unable to create user. Please correct the errors below.",
                        "danger",
                    )
                else:
                    status = "Administrator" if user.is_admin else "Standard user"
                    flash(
                        f"Created {status.lower()} account for {user.email}.", "success"
                    )
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
    from ..services.linux_users import get_available_linux_users

    available_linux_users = get_available_linux_users()
    for user in users:
        form = UserUpdateForm(formdata=None)
        form.user_id.data = str(user.id)
        form.name.data = user.name
        form.email.data = user.email
        form.is_admin.data = user.is_admin
        form.linux_username.data = user.linux_username or ""
        # Populate choices: empty option + available users
        form.linux_username.choices = [("", "None")] + [
            (u, u) for u in available_linux_users
        ]
        user_update_forms[user.id] = form

    ai_tool_cards = _build_ai_tool_cards()

    # API Keys
    api_key_create_form = APIKeyCreateForm()
    api_keys = APIKey.query.filter_by(user_id=current_user.id).order_by(
        APIKey.created_at.desc()
    ).all()
    api_key_revoke_forms = {
        key.id: APIKeyRevokeForm(key_id=str(key.id)) for key in api_keys
    }

    # Global Agent Context
    from ..forms.admin import GlobalAgentContextClearForm, GlobalAgentContextForm
    from ..models import GlobalAgentContext

    global_agent_context = GlobalAgentContext.query.order_by(
        GlobalAgentContext.updated_at.desc()
    ).first()
    global_agent_context_form = GlobalAgentContextForm()
    if global_agent_context:
        global_agent_context_form.content.data = global_agent_context.content
    global_agent_context_clear_form = GlobalAgentContextClearForm()

    # Database Backups
    backup_create_form = BackupCreateForm()
    backups = list_backups()
    backup_restore_forms = {
        backup["id"]: BackupRestoreForm(backup_id=backup["id"])
        for backup in backups
    }
    backup_delete_forms = {
        backup["id"]: BackupDeleteForm(backup_id=backup["id"])
        for backup in backups
    }

    # User Integration Credentials
    from ..models import TenantIntegration, UserIntegrationCredential

    user_credential_create_form = UserCredentialCreateForm()
    # Populate integration choices
    integrations = TenantIntegration.query.filter_by(enabled=True).order_by(
        TenantIntegration.name
    ).all()
    user_credential_create_form.integration_id.choices = [
        (i.id, f"{i.name} ({i.provider})") for i in integrations
    ]

    # Get user's existing credentials
    user_credentials = UserIntegrationCredential.query.filter_by(
        user_id=current_user.id
    ).all()
    user_credential_delete_forms = {
        cred.id: UserCredentialDeleteForm(credential_id=str(cred.id))
        for cred in user_credentials
    }

    # Load yadm (dotfiles) settings
    from ..forms.admin import YadmSettingsForm
    from ..models import SystemConfig

    yadm_form = YadmSettingsForm()
    dotfile_repo_url_config = SystemConfig.query.filter_by(
        key="dotfile_repo_url"
    ).first()
    dotfile_repo_branch_config = SystemConfig.query.filter_by(
        key="dotfile_repo_branch"
    ).first()
    dotfile_decrypt_password_config = SystemConfig.query.filter_by(
        key="dotfile_decrypt_password"
    ).first()

    if dotfile_repo_url_config and dotfile_repo_url_config.value:
        yadm_form.dotfile_repo_url.data = dotfile_repo_url_config.value.get("url", "")
    if dotfile_repo_branch_config and dotfile_repo_branch_config.value:
        yadm_form.dotfile_repo_branch.data = dotfile_repo_branch_config.value.get(
            "branch", "main"
        )

    yadm_password_configured = bool(dotfile_decrypt_password_config)

    return render_template(
        "admin/settings.html",
        update_form=update_form,
        migration_form=migration_form,
        tmux_resync_form=tmux_resync_form,
        permissions_check_form=permissions_check_form,
        permissions_fix_form=permissions_fix_form,
        create_user_form=create_user_form,
        users=users,
        user_toggle_forms=user_toggle_forms,
        user_reset_forms=user_reset_forms,
        user_delete_forms=user_delete_forms,
        user_update_forms=user_update_forms,
        restart_command=current_app.config.get("UPDATE_RESTART_COMMAND"),
        log_file=current_app.config.get("LOG_FILE"),
        quick_branch_form=quick_branch_form,
        ai_tool_cards=ai_tool_cards,
        api_key_create_form=api_key_create_form,
        api_keys=api_keys,
        api_key_revoke_forms=api_key_revoke_forms,
        global_agent_context=global_agent_context,
        global_agent_context_form=global_agent_context_form,
        global_agent_context_clear_form=global_agent_context_clear_form,
        backup_create_form=backup_create_form,
        backups=backups,
        backup_restore_forms=backup_restore_forms,
        backup_delete_forms=backup_delete_forms,
        user_credential_create_form=user_credential_create_form,
        user_credentials=user_credentials,
        user_credential_delete_forms=user_credential_delete_forms,
        yadm_form=yadm_form,
        now=datetime.utcnow(),
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
        log_message = (
            f"Application update command finished with exit {result.returncode}"
        )
        if combined_output:
            current_app.logger.info("%s; output: %s", log_message, combined_output)
        else:
            current_app.logger.info(log_message)
        if truncated:
            flash(
                Markup(
                    f'{escape(message)}<pre class="update-log">{escape(truncated)}</pre>'
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


@admin_bp.route("/system-status")
@admin_required
def system_status():
    """Display system status page."""
    return render_template("admin/system_status.html")


@admin_bp.route("/system/cleanup-sessions", methods=["POST"])
@admin_required
def cleanup_tmux_sessions():
    """Clean up stale AI sessions in the database and restart tmux servers."""
    from ..services.ai_session_service import cleanup_stale_sessions

    try:
        # Always restart tmux servers during cleanup
        result = cleanup_stale_sessions(restart_tmux=True)
        marked_inactive = result.get("marked_inactive", 0)
        total_checked = result.get("total_checked", 0)
        tmux_restarted = result.get("tmux_restarted", False)

        messages = []
        if tmux_restarted:
            messages.append("Tmux servers restarted")

        if marked_inactive > 0:
            messages.append(f"{marked_inactive} of {total_checked} sessions marked as inactive")
        else:
            messages.append(f"No sessions to clean up ({total_checked} checked)")

        flash(f"Cleanup completed: {'. '.join(messages)}.", "success")

    except Exception as exc:
        current_app.logger.exception("Session cleanup failed")
        flash(f"Session cleanup failed: {exc}", "danger")

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/ai-tools/<tool>/update", methods=["POST"])
@admin_required
def run_ai_tool_update_command(tool: str):
    form = AIToolUpdateForm()
    if not form.validate_on_submit():
        flash("Invalid AI CLI update request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    source = (form.source.data or "").strip().lower()
    redirect_target = form.next.data or url_for("admin.manage_settings")
    tool_key = tool.lower().strip()
    tool_label = {
        "codex": "Codex CLI",
        "claude": "Claude CLI",
    }.get(tool_key, tool.title())

    try:
        result = run_ai_tool_update(tool_key, source)
    except CLICommandError as exc:
        flash(str(exc), "danger")
        return redirect(redirect_target)

    combined_output = "\n".join(
        part for part in [result.stdout.strip(), result.stderr.strip()] if part
    )
    truncated = _truncate_output(combined_output)
    status = "succeeded" if result.ok else "failed"
    category = "success" if result.ok else "danger"
    message = (
        f"{tool_label} {source.upper()} command {status} (exit {result.returncode})."
    )
    if truncated:
        flash(
            Markup(
                f'{escape(message)}<pre class="update-log">{escape(truncated)}</pre>'
            ),
            category,
        )
    else:
        flash(message, category)

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


@admin_bp.route("/settings/api-keys/create", methods=["POST"])
@login_required
def create_api_key_web():
    """Create a new API key via web UI."""
    form = APIKeyCreateForm()
    if not form.validate_on_submit():
        flash("Invalid API key creation request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    name = (form.name.data or "").strip()
    if not name:
        flash("API key name is required.", "danger")
        return redirect(url_for("admin.manage_settings"))

    # Parse scopes from comma-separated string
    scopes_str = form.scopes.data or ""
    scopes = [s.strip() for s in scopes_str.split(",") if s.strip()]
    if not scopes:
        flash("At least one scope is required.", "danger")
        return redirect(url_for("admin.manage_settings"))

    # Parse expiration days
    expires_days = None
    expires_days_str = (form.expires_days.data or "").strip()
    if expires_days_str:
        try:
            expires_days = int(expires_days_str)
        except ValueError:
            flash("Invalid expiration days.", "danger")
            return redirect(url_for("admin.manage_settings"))

    # Generate API key
    from datetime import datetime, timedelta
    full_key, key_hash, key_prefix = APIKey.generate_key()

    # Calculate expiration if specified
    expires_at = None
    if expires_days and expires_days > 0:
        expires_at = datetime.utcnow() + timedelta(days=expires_days)

    # Create API key
    api_key = APIKey(
        user_id=current_user.id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=scopes,
        expires_at=expires_at,
    )
    db.session.add(api_key)
    db.session.commit()

    # Flash the full key (only shown once)
    flash(
        Markup(
            f'<strong>API key created successfully!</strong><br>'
            f'<span style="font-family: monospace; font-size: 1.1em; color: #059669;">{escape(full_key)}</span><br>'
            f'<small>Save this key securely - it won\'t be shown again.</small>'
        ),
        "success",
    )

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/api-keys/<int:key_id>/revoke", methods=["POST"])
@login_required
def revoke_api_key(key_id: int):
    """Revoke (delete) an API key."""
    form = APIKeyRevokeForm()
    if not form.validate_on_submit():
        flash("Invalid API key revocation request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    # Find the API key
    api_key = APIKey.query.filter_by(id=key_id, user_id=current_user.id).first()
    if not api_key:
        flash("API key not found or you don't have permission to revoke it.", "danger")
        return redirect(url_for("admin.manage_settings"))

    key_name = api_key.name
    db.session.delete(api_key)
    db.session.commit()

    flash(f'API key "{key_name}" has been revoked.', "success")
    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/user-credentials/create", methods=["POST"])
@login_required
def create_user_credential_web():
    """Create or update a user integration credential via web UI."""
    from ..models import TenantIntegration, UserIntegrationCredential

    form = UserCredentialCreateForm()

    # Populate integration choices (required for form validation)
    integrations = TenantIntegration.query.filter_by(enabled=True).order_by(
        TenantIntegration.name
    ).all()
    form.integration_id.choices = [
        (i.id, f"{i.name} ({i.provider})") for i in integrations
    ]

    if not form.validate_on_submit():
        current_app.logger.error(
            f"User credential form validation failed: {form.errors}"
        )
        flash("Invalid user credential request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    integration_id = form.integration_id.data
    api_token = form.api_token.data.strip() if form.api_token.data else ""

    # Verify integration exists
    integration = TenantIntegration.query.get(integration_id)
    if not integration:
        current_app.logger.error(
            f"Integration {integration_id} not found for user {current_user.id}"
        )
        flash("Integration not found.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        # Check if credential already exists for this user/integration
        existing = UserIntegrationCredential.query.filter_by(
            user_id=current_user.id, integration_id=integration_id
        ).first()

        if existing:
            # Update existing
            existing.api_token = api_token
            db.session.commit()
            current_app.logger.info(
                f"Updated personal token for user {current_user.id}, "
                f"integration {integration_id}"
            )
            flash(
                f'Personal token for "{integration.name}" updated successfully.',
                "success",
            )
        else:
            # Create new
            credential = UserIntegrationCredential(
                user_id=current_user.id,
                integration_id=integration_id,
                api_token=api_token,
            )
            db.session.add(credential)
            db.session.commit()
            current_app.logger.info(
                f"Created personal token for user {current_user.id}, "
                f"integration {integration_id}"
            )
            flash(
                f'Personal token for "{integration.name}" created successfully.',
                "success",
            )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            f"Error creating/updating user credential for user {current_user.id}, "
            f"integration {integration_id}: {exc}"
        )
        flash(
            "An error occurred while saving your personal token. Please try again.",
            "danger",
        )
        return redirect(url_for("admin.manage_settings"))

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/user-credentials/<int:credential_id>/delete", methods=["POST"])
@login_required
def delete_user_credential(credential_id: int):
    """Delete a user integration credential."""
    from ..models import UserIntegrationCredential

    form = UserCredentialDeleteForm()
    if not form.validate_on_submit():
        flash("Invalid delete request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    credential = UserIntegrationCredential.query.filter_by(
        id=credential_id, user_id=current_user.id
    ).first()

    if not credential:
        flash("Personal token not found.", "danger")
        return redirect(url_for("admin.manage_settings"))

    integration_name = credential.integration.name
    db.session.delete(credential)
    db.session.commit()

    flash(f'Personal token for "{integration_name}" removed.', "success")
    return redirect(url_for("admin.manage_settings"))


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
        log_message = (
            f"Database migration command finished with exit {result.returncode}"
        )
        if combined_output:
            current_app.logger.info("%s; output: %s", log_message, combined_output)
        else:
            current_app.logger.info(log_message)
        if truncated:
            flash(
                Markup(
                    f'{escape(message)}<pre class="update-log">{escape(truncated)}</pre>'
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
            linux_username=_current_linux_username(),
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


@admin_bp.route("/settings/permissions/check", methods=["POST"])
@admin_required
def check_instance_permissions():
    form = PermissionsCheckForm()
    if not form.validate_on_submit():
        flash("Invalid permissions check request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        instance_path = Path(current_app.config["INSTANCE_PATH"])
        result = check_permissions(instance_path)

        if result.errors:
            error_msg = Markup(
                "<strong>Permission check completed with errors:</strong><br>"
                + "<br>".join(escape(e) for e in result.errors)
            )
            flash(error_msg, "warning")
        elif result.issues_found > 0:
            issues_details = "<br>".join(
                f"• {escape(str(issue.path))}: {escape(issue.description)}"
                for issue in result.issues[:10]
            )
            if len(result.issues) > 10:
                issues_details += f"<br>... and {len(result.issues) - 10} more"

            flash(
                Markup(
                    f"<strong>Found {result.issues_found} permission issue(s) "
                    f"across {result.checked} path(s).</strong><br>"
                    f"{issues_details}<br><br>"
                    f"Click 'Fix Permissions' to resolve these issues."
                ),
                "warning",
            )
        else:
            flash(
                f"All permissions look good! Checked {result.checked} path(s).",
                "success",
            )
    except PermissionsError as exc:
        current_app.logger.exception("Failed to check permissions.")
        flash(str(exc), "danger")
    except Exception as exc:
        current_app.logger.exception("Unexpected error checking permissions.")
        flash(f"Unexpected error: {exc}", "danger")

    redirect_target = form.next.data or url_for("admin.manage_settings")
    return redirect(redirect_target)


@admin_bp.route("/settings/permissions/fix", methods=["POST"])
@admin_required
def fix_instance_permissions():
    form = PermissionsFixForm()
    if not form.validate_on_submit():
        flash("Invalid permissions fix request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        instance_path = Path(current_app.config["INSTANCE_PATH"])
        result = fix_permissions(instance_path)

        if result.errors:
            error_msg = Markup(
                f"<strong>Fixed {result.issues_fixed} of {result.issues_found} issue(s), "
                f"but encountered {len(result.errors)} error(s):</strong><br>"
                + "<br>".join(escape(e) for e in result.errors[:5])
            )
            if len(result.errors) > 5:
                error_msg += Markup(f"<br>... and {len(result.errors) - 5} more errors")
            flash(error_msg, "warning")
        elif result.issues_fixed > 0:
            flash(
                f"Successfully fixed {result.issues_fixed} permission issue(s) "
                f"across {result.checked} path(s).",
                "success",
            )
        else:
            flash(
                f"No permission issues found. Checked {result.checked} path(s).",
                "success",
            )
    except PermissionsError as exc:
        current_app.logger.exception("Failed to fix permissions.")
        flash(str(exc), "danger")
    except Exception as exc:
        current_app.logger.exception("Unexpected error fixing permissions.")
        flash(f"Unexpected error: {exc}", "danger")

    redirect_target = form.next.data or url_for("admin.manage_settings")
    return redirect(redirect_target)


@admin_bp.route("/settings/linux-user-mapping", methods=["POST"])
@admin_required
def save_linux_user_mapping():
    from ..services.linux_user_config_service import (
        save_linux_user_mapping as save_mapping,
    )

    form = LinuxUserMappingForm()
    if not form.validate_on_submit():
        flash("Invalid Linux user mapping configuration.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        mapping = json.loads(form.mapping_json.data)
        if not isinstance(mapping, dict):
            flash("Mapping must be a JSON object.", "danger")
            return redirect(url_for("admin.manage_settings"))

        # Validate that all keys and values are strings
        for key, value in mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                flash("All keys and values in mapping must be strings.", "danger")
                return redirect(url_for("admin.manage_settings"))

        save_mapping(mapping)
        flash("Saved Linux user mapping configuration.", "success")
    except json.JSONDecodeError:
        flash("Invalid JSON format for Linux user mapping.", "danger")
    except Exception as exc:
        current_app.logger.exception("Error saving Linux user mapping: %s", exc)
        flash("Error saving Linux user mapping configuration.", "danger")

    return redirect(url_for("admin.manage_settings"))


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

    return jsonify(
        {
            "ok": True,
            "content": tail.content,
            "truncated": tail.truncated,
            "path": str(log_path),
        }
    )


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
    from ..services.linux_users import get_available_linux_users

    form = UserUpdateForm()
    # Populate Linux user choices before validation
    available_linux_users = get_available_linux_users()
    linux_choice_items: ChoiceList = [("", "None")]
    linux_choice_items.extend((user, user) for user in available_linux_users)
    form.linux_username.choices = linux_choice_items

    if not form.validate_on_submit():
        error_messages = [
            message for messages in form.errors.values() for message in messages
        ]
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
    # Set linux_username, allowing empty string to clear the selection
    linux_username = (form.linux_username.data or "").strip()
    user.linux_username = linux_username if linux_username else None

    # Update AIOPS CLI credentials from request form
    aiops_cli_url = request.form.get("aiops_cli_url", "").strip()
    aiops_cli_api_key = request.form.get("aiops_cli_api_key", "").strip()
    user.aiops_cli_url = aiops_cli_url if aiops_cli_url else None
    user.aiops_cli_api_key = aiops_cli_api_key if aiops_cli_api_key else None

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
        selectinload(Project.issue_integrations).selectinload(
            ProjectIntegration.integration
        ),
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
        current_app.logger.exception(
            "Issue refresh failed for project_id=%s", project_id
        )
        flash("Unexpected error while refreshing issues.", "danger")
    else:
        if total_synced:
            flash(
                f"Refreshed issues for {project.name} ({total_synced} updated).",
                "success",
            )
        elif force_full:
            flash(
                f"Refreshed issues for {project.name}. No new updates detected.",
                "success",
            )
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
        # Use current user's workspace for git operations
        user_obj = getattr(current_user, "model", None)
        output = run_git_action(
            project, "pull", ref=branch_name, clean=clean_requested, user=user_obj
        )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Git pull failed for project_id=%s", project_id)
        flash(f"Git pull failed: {exc}", "danger")
    else:
        if clean_requested:
            flash(f"Clean pull completed for {project.name}.", "success")
        else:
            branch_label = branch_name or project.default_branch
            flash(
                f"Pulled latest changes for {project.name} ({branch_label}).", "success"
            )
        current_app.logger.info(
            "Git pull for project %s (clean=%s): %s",
            project.name,
            clean_requested,
            output,
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
            flash(
                f"Merged {source_branch} into {target_branch} for {project.name}.",
                "success",
            )
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


@admin_bp.route("/issues/create-assisted", methods=["GET", "POST"])
@admin_required
def create_assisted_issue():
    """Create an issue with AI assistance (Step 1: Generate preview)."""
    import json
    from ..forms.admin import AIAssistedIssueForm
    from ..models import ProjectIntegration
    from ..services.ai_issue_generator import (
        AIIssueGenerationError,
        generate_issue_from_description,
    )

    # Populate project choices and build integration map
    projects = Project.query.order_by(Project.name).all()
    project_choices = [(p.id, f"{p.tenant.name} / {p.name}") for p in projects]

    # Build a map of project_id to first integration_id for JavaScript
    project_integrations = {}
    for project in projects:
        integration = ProjectIntegration.query.filter_by(
            project_id=project.id
        ).first()
        if integration:
            project_integrations[project.id] = integration.id

    # Create form - Flask-WTF will auto-populate from request on POST
    form = AIAssistedIssueForm()
    form.project_id.choices = project_choices

    # Populate creator_user_id choices with all users
    users = User.query.order_by(User.name).all()
    form.creator_user_id.choices = [(u.id, u.name) for u in users]
    # Set default to current user
    if users and not request.form.get('creator_user_id'):
        form.creator_user_id.data = current_user.id

    # Populate integration_id choices based on selected project
    # This is needed for form validation to work on both GET and POST
    if request.method == 'POST' and request.form.get('project_id'):
        # On POST, get the selected project_id from form data
        try:
            selected_project_id = int(request.form.get('project_id'))
            integrations = ProjectIntegration.query.filter_by(
                project_id=selected_project_id
            ).all()
            form.integration_id.choices = [
                (i.id, f"{i.integration.provider.upper()} - {i.integration.name}")
                for i in integrations
            ]
        except (ValueError, TypeError):
            form.integration_id.choices = []
    else:
        # On GET, leave empty and let JavaScript populate it
        form.integration_id.choices = []

    # Check if form is submitted and valid
    if form.validate_on_submit():
        # Handle form submission - generate preview
        project_id = form.project_id.data
        integration_id = form.integration_id.data
        description = form.description.data
        ai_tool = form.ai_tool.data
        issue_type = form.issue_type.data if form.issue_type.data else None

        # Get integration and project
        integration = ProjectIntegration.query.get(integration_id)
        if not integration or integration.project_id != project_id:
            flash("Invalid integration selected for this project", "error")
            return render_template(
                "admin/create_assisted_issue.html",
                form=form,
                project_integrations_json=json.dumps(project_integrations),
            )

        project = db.session.get(Project, project_id)
        if not project:
            flash("Project not found", "error")
            return render_template(
                "admin/create_assisted_issue.html",
                form=form,
                project_integrations_json=json.dumps(project_integrations),
            )

        try:
            # Step 1: Generate issue preview
            import time
            generation_start = time.time()
            try:
                issue_data = generate_issue_from_description(
                    description, ai_tool, issue_type, user_id=current_user.id
                )
            except AIIssueGenerationError as exc:
                flash(f"AI generation failed: {exc}", "error")
                return render_template(
                    "admin/create_assisted_issue.html",
                    form=form,
                    project_integrations_json=json.dumps(project_integrations),
                )
            generation_time = time.time() - generation_start

            # Step 2: Encode preview data and show preview page
            creator_user_id = form.creator_user_id.data

            # Encode all preview data as JSON to pass through form
            # This avoids session persistence issues
            preview_data = {
                "project_id": project_id,
                "integration_id": integration.id,
                "issue_data": issue_data,
                "ai_tool": ai_tool,
                "issue_type": issue_type,
                "description": description,
                "creator_user_id": creator_user_id,
            }
            preview_json = json.dumps(preview_data)

            return render_template(
                "admin/preview_assisted_issue.html",
                issue_data=issue_data,
                preview_json=preview_json,
                project=project,
                integration=integration.integration,
                current_user=current_user,
                ai_tool=ai_tool,
                generation_time=generation_time,
            )

        except Exception as e:
            flash(f"Failed to generate issue preview: {e}", "error")
            current_app.logger.exception("Error generating AI-assisted issue preview")

    return render_template(
        "admin/create_assisted_issue.html",
        form=form,
        project_integrations_json=json.dumps(project_integrations),
    )


@admin_bp.route("/issues/confirm-assisted", methods=["POST"])
@admin_required
def confirm_assisted_issue():
    """Create an issue with AI assistance (Step 2: Confirm and create)."""
    from ..models import ProjectIntegration, ExternalIssue
    from ..services.issues import (
        create_issue_for_project_integration,
        serialize_issue_comments,
    )
    from datetime import datetime, timezone

    # Get preview data from form
    preview_json = request.form.get("preview_data")
    if not preview_json:
        flash("Preview data missing", "error")
        return redirect(url_for("admin.create_assisted_issue"))

    # Decode preview data from JSON
    try:
        preview_data = json.loads(preview_json)
    except (json.JSONDecodeError, ValueError):
        flash("Preview data is invalid. Please try again.", "error")
        return redirect(url_for("admin.create_assisted_issue"))

    project_id = preview_data["project_id"]
    integration_id = preview_data["integration_id"]
    issue_data = preview_data["issue_data"]
    ai_tool = preview_data["ai_tool"]
    issue_type = preview_data["issue_type"]
    creator_user_id = preview_data.get("creator_user_id", current_user.id)

    # Get integration and project
    integration = ProjectIntegration.query.get(integration_id)
    if not integration or integration.project_id != project_id:
        flash("Integration not found", "error")
        return redirect(url_for("admin.create_assisted_issue"))

    project = db.session.get(Project, project_id)
    if not project:
        flash("Project not found", "error")
        return redirect(url_for("admin.create_assisted_issue"))

    try:
        # Create issue in external tracker
        branch_prefix = issue_data.get("branch_prefix", "feature")
        labels = issue_data.get("labels", []) or []

        issue_payload = create_issue_for_project_integration(
            project_integration=integration,
            summary=issue_data["title"],
            description=issue_data["description"],
            labels=labels,
            issue_type=issue_type or None,
            assignee_user_id=current_user.id,
            creator_user_id=creator_user_id,
        )

        # Create ExternalIssue record in database
        issue = ExternalIssue(
            project_integration_id=integration.id,
            external_id=issue_payload.external_id,
            title=issue_payload.title,
            status=issue_payload.status,
            assignee=issue_payload.assignee,
            url=issue_payload.url,
            labels=issue_payload.labels or [],
            external_updated_at=issue_payload.external_updated_at,
            last_seen_at=datetime.now(timezone.utc),
            raw_payload=issue_payload.raw,
            comments=serialize_issue_comments(issue_payload.comments or []),
        )
        db.session.add(issue)
        db.session.commit()

        flash(f"Issue created: #{issue.external_id}", "success")

        # Write tracked AGENTS.override.md with structured issue context
        from ..services.agent_context import write_tracked_issue_context

        context_path, sources = write_tracked_issue_context(
            project=project,
            primary_issue=issue,
            all_issues=[issue],
            identity_user=current_user.model,
        )

        # Launch AI session in a dedicated tmux session for AI-assisted issues
        from ..ai_sessions import create_session
        current_app.logger.warning(f"DEBUG: Creating AI session with tool={ai_tool} for issue #{issue.external_id}")
        session = create_session(
            project=project,
            user_id=current_user.id,
            tool=ai_tool,
            issue_id=issue.id,
            tmux_session_name="ai-assist",  # Use dedicated session for AI-assisted issues
        )

        # Inform user about context sources
        sources_msg = " + ".join(sources) if sources else "project defaults"
        flash(f"AI session started for issue #{issue.external_id}", "success")
        flash(f"AGENTS.override.md populated from: {sources_msg}", "info")

        # Pass CLI commands to success page
        cli_commands = {
            "work_on_issue": f"aiops issues work {issue.id} --tool {ai_tool}",
            "get_details": f"aiops issues get {issue.id} --output json",
            "add_comment": f"aiops issues comment {issue.id} \"Your update\"",
            "close_issue": f"aiops issues close {issue.id}",
        }

        return render_template(
            "admin/assisted_issue_success.html",
            issue=issue,
            project=project,
            ai_tool=ai_tool,
            session_target=session.tmux_target,
            cli_commands=cli_commands,
            sources_msg=sources_msg,
        )

    except Exception as e:
        flash(f"Failed to create assisted issue: {e}", "error")
        current_app.logger.exception("Error creating AI-assisted issue")
        return redirect(url_for("admin.create_assisted_issue"))


@admin_bp.route("/issues", methods=["GET", "POST"])
@admin_required
def manage_issues():
    (
        creation_link_map,
        creation_choices,
        creation_metadata,
    ) = _build_issue_creation_targets()
    (
        assignee_choices,
        identity_lookup,
        assignee_capabilities,
    ) = _build_assignee_choices()

    issue_create_form = IssueDashboardCreateForm(prefix="issue-create")
    issue_create_form.project_integration_id.choices = creation_choices
    issue_create_form.assignee_user_id.choices = assignee_choices
    if (
        creation_choices
        and issue_create_form.project_integration_id.data is None
        and request.method == "GET"
    ):
        issue_create_form.project_integration_id.data = creation_choices[0][0]
    custom_field_values = (
        {key: value for key, value in request.form.items() if key.startswith("custom_field__")}
        if request.method == "POST"
        else {}
    )
    custom_field_errors: dict[str, str] = {}
    issue_create_modal_open = bool(
        request.method == "POST" and issue_create_form.submit.data
    )
    if issue_create_form.submit.data:
        form_valid = issue_create_form.validate_on_submit()
        link = creation_link_map.get(issue_create_form.project_integration_id.data)
        if link is None:
            issue_create_form.project_integration_id.errors.append(
                "Please choose a project integration."
            )
            form_valid = False
        custom_payload: dict[str, Any] | None = None
        field_definitions = _normalize_custom_fields(link.config or {}) if link else []
        if link:
            custom_payload, custom_field_errors = _extract_custom_field_values(
                field_definitions, request.form
            )
            if custom_field_errors:
                form_valid = False

        assignee_user_id = issue_create_form.assignee_user_id.data or 0
        provider_key = (
            (link.integration.provider or "").lower()
            if link and link.integration
            else ""
        )
        if assignee_user_id and provider_key:
            identity = identity_lookup.get(assignee_user_id)
            has_mapping = False
            if provider_key == "github":
                has_mapping = bool(identity and identity.github_username)
            elif provider_key == "gitlab":
                has_mapping = bool(identity and identity.gitlab_username)
            elif provider_key == "jira":
                has_mapping = bool(identity and identity.jira_account_id)
            if not has_mapping:
                issue_create_form.assignee_user_id.errors.append(
                    "Selected user lacks the required identity mapping."
                )
                form_valid = False

        if form_valid and link is not None:
            summary = (issue_create_form.summary.data or "").strip()
            description = (issue_create_form.description.data or "").strip() or None
            issue_type_value = (
                (issue_create_form.issue_type.data or "").strip() or None
            )
            labels_raw = issue_create_form.labels.data or ""
            labels = [
                label.strip() for label in labels_raw.split(",") if label.strip()
            ]
            milestone_value = (issue_create_form.milestone.data or "").strip() or None
            priority_value = (issue_create_form.priority.data or "").strip() or None
            assignee_value = assignee_user_id or None
            try:
                payload = create_issue_for_project_integration(
                    link,
                    summary=summary,
                    description=description,
                    issue_type=issue_type_value,
                    labels=labels or None,
                    milestone=milestone_value,
                    priority=priority_value,
                    custom_fields=(custom_payload or None),
                    assignee_user_id=assignee_value,
                    creator_user_id=current_user.id,
                )
                sync_project_integration(link)
                db.session.commit()
            except IssueSyncError as exc:
                db.session.rollback()
                flash(f"Failed to create issue: {exc}", "danger")
            except Exception:  # noqa: BLE001
                db.session.rollback()
                current_app.logger.exception(
                    "Issue creation failed for project_integration_id=%s",
                    link.id,
                )
                flash("Unexpected error while creating the issue.", "danger")
            else:
                issue_create_modal_open = False
                integration = link.integration
                provider_display = (
                    (
                        integration.name
                        or (integration.provider or "Integration").title()
                    )
                    if integration
                    else "Integration"
                )
                current_app.logger.info(
                    "Issue %s created via %s by user_id=%s",
                    payload.external_id,
                    provider_display,
                    current_user.id,
                )
                flash(
                    f"Created issue {payload.external_id} via {provider_display}.",
                    "success",
                )
                return redirect(url_for("admin.manage_issues"))
        elif request.method == "POST" and issue_create_form.submit.data:
            flash("Please correct the errors in the issue form.", "danger")

    issues = ExternalIssue.query.options(
        selectinload(ExternalIssue.project_integration)
        .selectinload(ProjectIntegration.project)
        .selectinload(Project.tenant),
        selectinload(ExternalIssue.project_integration).selectinload(
            ProjectIntegration.integration
        ),
    ).all()

    sorted_issues = sorted(issues, key=_issue_sort_key, reverse=True)

    # Get pinned issues for the current user
    from ..models import PinnedIssue

    pinned_issue_ids = {
        pinned.issue_id
        for pinned in PinnedIssue.query.filter_by(user_id=current_user.id).all()
    }

    # Build a set of tenant IDs that have multiple projects (for "Move to..." feature)
    tenant_project_counts: dict[int, int] = {}
    for tenant in Tenant.query.all():
        project_count = Project.query.filter_by(tenant_id=tenant.id).count()
        tenant_project_counts[tenant.id] = project_count
    tenants_with_multiple_projects = {
        tid for tid, count in tenant_project_counts.items() if count > 1
    }

    tenant_counts: Counter[str] = Counter()
    tenant_labels: dict[str, str] = {}
    project_counts: Counter[str] = Counter()
    project_labels: dict[str, str] = {}
    assignee_counts: Counter[str] = Counter()
    assignee_labels: dict[str, str] = {}
    for issue in issues:
        project = (
            issue.project_integration.project if issue.project_integration else None
        )
        project_key = str(project.id) if project else "__unknown__"
        project_label = project.name if project else "Unknown project"
        project_counts[project_key] += 1
        project_labels.setdefault(project_key, project_label)

        tenant = project.tenant if project else None
        tenant_key = str(tenant.id) if tenant else "__unknown__"
        tenant_label = tenant.name if tenant else "Unknown tenant"
        tenant_counts[tenant_key] += 1
        tenant_labels.setdefault(tenant_key, tenant_label)

        # Track assignees
        assignee_key = issue.assignee if issue.assignee else "__unassigned__"
        assignee_label = issue.assignee if issue.assignee else "Unassigned"
        assignee_counts[assignee_key] += 1
        assignee_labels.setdefault(assignee_key, assignee_label)

    status_counts: Counter[str] = Counter()
    status_labels: dict[str, str] = {}
    issue_entries: list[dict[str, object]] = []
    provider_statuses: dict[str, set[str]] = defaultdict(set)
    ai_tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    default_ai_shell = current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    codex_command = ai_tool_commands.get("codex", default_ai_shell)

    for issue in sorted_issues:
        status_key, status_label = normalize_issue_status(issue.status)
        status_counts[status_key] += 1
        status_labels.setdefault(status_key, status_label)

        integration = (
            issue.project_integration.integration if issue.project_integration else None
        )
        project = (
            issue.project_integration.project if issue.project_integration else None
        )
        tenant = project.tenant if project else None
        provider_key = (
            (integration.provider or "").lower()
            if integration and integration.provider
            else ""
        )

        updated_reference = (
            issue.external_updated_at or issue.updated_at or issue.created_at
        )

        description_text = extract_issue_description(issue)
        description_html = extract_issue_description_html(issue)
        comment_entries = _prepare_comment_entries(getattr(issue, "comments", []))

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
                "project_key": str(project.id) if project else "__unknown__",
                "tenant_name": tenant.name if tenant else "",
                "tenant_id": tenant.id if tenant else None,
                "tenant_color": tenant.color if tenant else DEFAULT_TENANT_COLOR,
                "updated_display": _format_issue_timestamp(updated_reference),
                "updated_sort": _issue_sort_key(issue),
                "description": description_text,
                "description_html": description_html,
                "description_available": bool(description_text or description_html),
                "description_fallback": MISSING_ISSUE_DETAILS_MESSAGE,
                "comments": comment_entries,
                "comment_count": len(comment_entries),
                "is_pinned": issue.id in pinned_issue_ids,
                "prepare_endpoint": url_for(
                    "projects.prepare_issue_context",
                    project_id=project.id,
                    issue_id=issue.id,
                )
                if project
                else None,
                "codex_target": url_for(
                    "projects.project_ai_console", project_id=project.id, issue_id=issue.id
                )
                if project
                else None,
                "codex_payload": {
                    "prompt": "",
                    "command": codex_command,
                    "tool": "codex",
                    "autoStart": True,
                    "issueId": issue.id,
                    "agentPath": None,
                    "tmuxTarget": None,
                }
                if project
                else None,
                "populate_endpoint": url_for(
                    "projects.populate_issue_agents_md",
                    project_id=project.id,
                    issue_id=issue.id,
                )
                if project
                else None,
                "close_endpoint": url_for(
                    "projects.close_issue", project_id=project.id, issue_id=issue.id
                )
                if project
                else None,
                "can_close": status_key != "closed",
                "status_update_endpoint": url_for(
                    "admin.update_issue_status", issue_id=issue.id
                ),
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
    project_raw_filter = (request.args.get("project") or "").strip()
    assignee_raw_filter = (request.args.get("assignee") or "").strip()
    raw_sort = (request.args.get("sort") or "").strip().lower()
    sort_key = raw_sort if raw_sort in ISSUE_SORT_META else ISSUE_SORT_DEFAULT_KEY
    raw_direction = (request.args.get("direction") or "").strip().lower()
    target_issue_id = request.args.get("issue_id")

    if raw_direction not in {"asc", "desc"}:
        sort_direction = ISSUE_SORT_META[sort_key]["default_direction"]
    else:
        sort_direction = raw_direction

    default_filter = "open"

    # If targeting a specific issue via issue_id parameter, always show all statuses to ensure the issue is found
    if target_issue_id:
        status_filter = "all"
        current_app.logger.info(f"[Issue #158] Pinned issue mode: forcing status_filter='all' to show target issue {target_issue_id}")
    elif raw_filter == "all":
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

    if project_raw_filter and project_raw_filter.lower() != "all":
        if project_raw_filter in project_labels:
            project_filter = project_raw_filter
        else:
            project_filter = "all"
    else:
        project_filter = "all"

    # Get current user's name for "My Issues" matching
    current_user_name = current_user.name if hasattr(current_user, "name") else None

    # Handle assignee filter
    if assignee_raw_filter and assignee_raw_filter.lower() != "all":
        if assignee_raw_filter == "__me__":
            # Special filter for "My Issues"
            assignee_filter = "__me__"
        elif assignee_raw_filter in assignee_labels:
            assignee_filter = assignee_raw_filter
        else:
            assignee_filter = "all"
    else:
        assignee_filter = "all"

    def _matches(entry: dict[str, object]) -> bool:
        if status_filter != "all" and entry.get("status_key") != status_filter:
            return False
        if tenant_filter != "all":
            entry_tenant = entry.get("tenant_id")
            entry_key = str(entry_tenant) if entry_tenant is not None else "__unknown__"
            if entry_key != tenant_filter:
                return False
        if project_filter != "all":
            entry_project = entry.get("project_key") or "__unknown__"
            if entry_project != project_filter:
                return False
        if assignee_filter != "all":
            entry_assignee = entry.get("assignee") or "__unassigned__"
            if assignee_filter == "__me__":
                # Match current user's name
                if current_user_name and entry.get("assignee") == current_user_name:
                    return True
                return False
            elif entry_assignee != assignee_filter:
                return False
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
        "labels": _string_sort_key(
            "labels", transform=lambda labels: ", ".join(labels or [])
        ),
        "updated": lambda entry: entry.get("updated_sort"),
    }

    key_func = sort_key_functions.get(
        sort_key, sort_key_functions[ISSUE_SORT_DEFAULT_KEY]
    )
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

    for status_key, status_label in sorted(
        status_labels.items(), key=_status_option_sort_key
    ):
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

    project_options = [
        {
            "value": "all",
            "label": "All projects",
            "count": total_issue_full_count,
        }
    ]

    for key, label in sorted(project_labels.items(), key=lambda item: item[1].lower()):
        project_options.append(
            {
                "value": key,
                "label": label,
                "count": project_counts.get(key, 0),
            }
        )

    project_filter_label = (
        "All projects"
        if project_filter == "all"
        else project_labels.get(project_filter, project_filter)
    )

    # Build assignee options
    assignee_options = [
        {
            "value": "all",
            "label": "All assignees",
            "count": total_issue_full_count,
        }
    ]

    # Add "My Issues" option if user has a name
    if current_user_name:
        my_issues_count = sum(
            1 for entry in issue_entries if entry.get("assignee") == current_user_name
        )
        assignee_options.append(
            {
                "value": "__me__",
                "label": f"My Issues ({current_user_name})",
                "count": my_issues_count,
            }
        )

    # Add all other assignees
    for key, label in sorted(assignee_labels.items(), key=lambda item: item[1].lower()):
        assignee_options.append(
            {
                "value": key,
                "label": label,
                "count": assignee_counts.get(key, 0),
            }
        )

    assignee_filter_label = (
        "All assignees"
        if assignee_filter == "all"
        else f"My Issues ({current_user_name})"
        if assignee_filter == "__me__"
        else assignee_labels.get(assignee_filter, assignee_filter)
    )

    sort_state = {"key": sort_key, "direction": sort_direction}
    sort_columns = [dict(column) for column in ISSUE_SORT_COLUMNS]

    base_query_params: dict[str, str] = {}
    if "status" in request.args:
        base_query_params["status"] = status_filter
    if "tenant" in request.args:
        base_query_params["tenant"] = tenant_filter
    if "project" in request.args:
        base_query_params["project"] = project_filter
    if "assignee" in request.args:
        base_query_params["assignee"] = assignee_filter

    sort_headers: dict[str, dict[str, object]] = {}
    for column in sort_columns:
        column_key = column["key"]
        is_active = column_key == sort_key
        current_direction = sort_direction if is_active else None
        if is_active:
            next_direction = "asc" if sort_direction == "desc" else "desc"
        else:
            next_direction = column["default_direction"]

        query_params = {
            **base_query_params,
            "sort": column_key,
            "direction": next_direction,
        }
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
        project_filter=project_filter,
        project_filter_label=project_filter_label,
        project_options=project_options,
        assignee_filter=assignee_filter,
        assignee_filter_label=assignee_filter_label,
        assignee_options=assignee_options,
        total_issue_count=total_issue_count,
        total_issue_full_count=total_issue_full_count,
        sort_columns=sort_columns,
        sort_headers=sort_headers,
        sort_state=sort_state,
        sort_key=sort_key,
        sort_direction=sort_direction,
        issue_status_max_length=ISSUE_STATUS_MAX_LENGTH,
        current_view_url=current_view_url,
        current_user_name=current_user_name,
        ai_tool_commands=ai_tool_commands,
        default_ai_shell=default_ai_shell,
        issue_create_form=issue_create_form,
        issue_create_options=creation_metadata,
        issue_create_modal_open=issue_create_modal_open,
        issue_create_capabilities=assignee_capabilities,
        issue_custom_field_values=custom_field_values,
        issue_custom_field_errors=custom_field_errors,
        target_issue_id=target_issue_id,
        tenants_with_multiple_projects=tenants_with_multiple_projects,
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
        current_app.logger.exception(
            "Failed to update issue status", extra={"issue_id": issue_id}
        )
        flash("Unexpected error while updating issue status.", "danger")
    else:
        status_label = issue.status or "unspecified"
        flash(
            f"Updated status for issue {issue.external_id} to {status_label}.",
            "success",
        )

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
            flash(
                f"Refreshed issues across all integrations ({total_updated} updated).",
                "success",
            )
        elif force_full:
            flash(
                "Completed full issue resync with no new changes detected.", "success"
            )
        else:
            flash("Issue caches are already up to date.", "success")

    return redirect(url_for("admin.manage_issues"))


@admin_bp.route("/projects", methods=["GET", "POST"])
@admin_required
def manage_projects():
    form = ProjectForm()
    delete_form = ProjectDeleteForm()
    form.tenant_id.choices = [
        (t.id, t.name) for t in Tenant.query.order_by(Tenant.name)
    ]
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
        # Slugify project name for filesystem path
        def _slugify(name: str) -> str:
            cleaned = "".join(char.lower() if char.isalnum() else "-" for char in name)
            cleaned = "-".join(filter(None, cleaned.split("-")))
            return cleaned or "project"

        storage_root = Path(current_app.config["REPO_STORAGE_PATH"])
        storage_root.mkdir(parents=True, exist_ok=True)
        slug = _slugify(form.name.data)
        local_path = storage_root / slug

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

        try:
            ensure_repo_checkout(project)
            flash("Project registered and repository cloned.", "success")
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(
                "Failed to clone repository for project %s: %s", project.name, exc
            )
            flash(
                f"Project registered but repository clone failed: {exc}. "
                "You can try cloning manually later.",
                "warning"
            )
        return redirect(url_for("admin.manage_projects"))

    projects = Project.query.order_by(Project.created_at.desc()).all()
    return render_template(
        "admin/projects.html", form=form, delete_form=delete_form, projects=projects
    )


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

    if (
        integration_delete_form.submit.data
        and integration_delete_form.validate_on_submit()
    ):
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
                    integration_form.jira_email.errors.append(
                        "Enter a valid email address."
                    )
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

            # Prepare per-project credential overrides
            override_api_token = (project_form.override_api_token.data or "").strip() or None
            override_base_url = (project_form.override_base_url.data or "").strip() or None
            override_settings: dict[str, str] | None = None
            override_username = (project_form.override_username.data or "").strip()
            if override_username:
                override_settings = {"username": override_username}

            project_integration = ProjectIntegration(
                project_id=project.id,
                integration_id=integration.id,
                external_identifier=project_form.external_identifier.data.strip(),
                config=config,
                override_api_token=override_api_token,
                override_base_url=override_base_url,
                override_settings=override_settings,
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
            # Pre-fill override credential fields
            update_form.override_base_url.data = link.override_base_url or ""
            if link.override_settings:
                update_form.override_username.data = link.override_settings.get("username", "")
            delete_form = ProjectIntegrationDeleteForm(prefix=f"delete-{link.id}")
            update_forms[link.id] = update_form
            delete_forms[link.id] = delete_form

    # Create update forms for tenant integrations
    tenant_integration_update_forms: dict[int, TenantIntegrationUpdateForm] = {}
    for integration in integrations:
        update_form = TenantIntegrationUpdateForm(prefix=f"update-tenant-{integration.id}")
        update_form.name.data = integration.name
        update_form.base_url.data = integration.base_url or ""
        tenant_integration_update_forms[integration.id] = update_form

    return render_template(
        "admin/integrations.html",
        integration_form=integration_form,
        integration_delete_form=integration_delete_form,
        project_form=project_form,
        integrations=integrations,
        integration_update_forms=update_forms,
        integration_delete_forms=delete_forms,
        tenant_integration_update_forms=tenant_integration_update_forms,
    )


@admin_bp.route("/integrations/<int:integration_id>", methods=["GET", "POST"])
@admin_required
def integration_detail(integration_id: int):
    """View and manage all projects mapped to a specific integration."""
    integration = TenantIntegration.query.options(
        selectinload(TenantIntegration.tenant),
        selectinload(TenantIntegration.project_integrations).selectinload(
            ProjectIntegration.project
        ),
    ).get_or_404(integration_id)

    # Form for adding new project mappings
    add_project_form = ProjectIntegrationForm(prefix="add")

    # Get all projects in the same tenant
    available_projects = Project.query.filter_by(
        tenant_id=integration.tenant_id
    ).order_by(Project.name).all()

    # Filter out already mapped projects
    mapped_project_ids = {link.project_id for link in integration.project_integrations}
    unmapped_projects = [p for p in available_projects if p.id not in mapped_project_ids]

    # Set up choices for the form (both fields are SelectFields and need choices)
    project_choices = [(p.id, p.name) for p in unmapped_projects]
    add_project_form.project_id.choices = project_choices
    add_project_form.integration_id.choices = [(integration.id, integration.name)]
    add_project_form.integration_id.data = integration.id

    # Handle form submission for adding a new project mapping
    if add_project_form.link.data and add_project_form.validate_on_submit():
        project = Project.query.get(add_project_form.project_id.data)

        if project and project.tenant_id == integration.tenant_id:
            # Check for existing link
            existing_link = ProjectIntegration.query.filter_by(
                integration_id=integration.id,
                project_id=project.id,
            ).first()

            if existing_link:
                flash(f"Project '{project.name}' is already linked to this integration.", "warning")
            else:
                # Prepare config
                config: dict[str, str] = {}
                jira_jql = (add_project_form.jira_jql.data or "").strip()
                if jira_jql and integration.provider.lower() == "jira":
                    config["jql"] = jira_jql

                # Prepare per-project credential overrides
                override_api_token = (add_project_form.override_api_token.data or "").strip() or None
                override_base_url = (add_project_form.override_base_url.data or "").strip() or None
                override_settings: dict[str, str] | None = None
                override_username = (add_project_form.override_username.data or "").strip()
                if override_username:
                    override_settings = {"username": override_username}

                # Create the link
                project_integration = ProjectIntegration(
                    project_id=project.id,
                    integration_id=integration.id,
                    external_identifier=add_project_form.external_identifier.data.strip(),
                    config=config,
                    override_api_token=override_api_token,
                    override_base_url=override_base_url,
                    override_settings=override_settings,
                )
                db.session.add(project_integration)
                db.session.commit()
                flash(f"Project '{project.name}' successfully linked to integration.", "success")
                return redirect(url_for("admin.integration_detail", integration_id=integration.id))
        else:
            flash("Invalid project selection.", "danger")

    # Create update and delete forms for existing mappings
    update_forms: dict[int, ProjectIntegrationUpdateForm] = {}
    delete_forms: dict[int, ProjectIntegrationDeleteForm] = {}

    for link in integration.project_integrations:
        # Update form
        update_form = ProjectIntegrationUpdateForm(prefix=f"update-{link.id}")
        update_form.external_identifier.data = link.external_identifier
        if integration.provider.lower() == "jira":
            update_form.jira_jql.data = (link.config or {}).get("jql", "")
        update_form.override_base_url.data = link.override_base_url or ""
        if link.override_settings:
            update_form.override_username.data = link.override_settings.get("username", "")
        update_forms[link.id] = update_form

        # Delete form
        delete_form = ProjectIntegrationDeleteForm(prefix=f"delete-{link.id}")
        delete_forms[link.id] = delete_form

    # Sort project integrations by project name
    sorted_links = sorted(
        integration.project_integrations,
        key=lambda link: link.project.name if link.project else ""
    )

    return render_template(
        "admin/integration_detail.html",
        integration=integration,
        project_integrations=sorted_links,
        add_project_form=add_project_form,
        update_forms=update_forms,
        delete_forms=delete_forms,
        unmapped_projects=unmapped_projects,
        has_unmapped_projects=len(unmapped_projects) > 0,
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
        return jsonify(
            {"ok": False, "message": "Provider and API token are required."}
        ), 400

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
        message = test_integration_connection(
            provider, api_token, base_url, username=username
        )
    except IssueSyncError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    return jsonify({"ok": True, "message": message})


@admin_bp.route(
    "/integrations/project/<int:project_integration_id>/update", methods=["POST"]
)
@admin_required
def update_project_integration(project_integration_id: int):
    link = ProjectIntegration.query.options(
        selectinload(ProjectIntegration.integration).selectinload(
            TenantIntegration.tenant
        ),
        selectinload(ProjectIntegration.project),
    ).get_or_404(project_integration_id)

    prefix = f"update-{project_integration_id}"
    form = ProjectIntegrationUpdateForm(prefix=prefix)
    prefixed_field = f"{prefix}-external_identifier"
    if prefixed_field not in request.form and "external_identifier" in request.form:
        form = ProjectIntegrationUpdateForm()
    if not form.validate_on_submit():
        flash(
            "Unable to update project integration. Please fix the form errors.",
            "danger",
        )
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

    # Update per-project credential overrides
    override_api_token = (form.override_api_token.data or "").strip()
    if override_api_token:
        link.override_api_token = override_api_token
    # Note: If blank, we keep the existing token (don't clear it)

    override_base_url = (form.override_base_url.data or "").strip() or None
    link.override_base_url = override_base_url

    override_username = (form.override_username.data or "").strip()
    if override_username:
        link.override_settings = {"username": override_username}
    else:
        link.override_settings = None

    db.session.commit()

    flash("Project integration updated.", "success")
    return redirect(url_for("admin.manage_integrations"))


@admin_bp.route(
    "/integrations/project/<int:project_integration_id>/delete", methods=["POST"]
)
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


@admin_bp.route("/integrations/<int:integration_id>/update", methods=["POST"])
@admin_required
def update_tenant_integration(integration_id: int):
    integration = TenantIntegration.query.get_or_404(integration_id)

    prefix = f"update-tenant-{integration_id}"
    form = TenantIntegrationUpdateForm(prefix=prefix)

    # Handle both prefixed and non-prefixed form submissions
    prefixed_field = f"{prefix}-name"
    if prefixed_field not in request.form and "name" in request.form:
        form = TenantIntegrationUpdateForm()

    if not form.validate_on_submit():
        flash("Unable to update integration. Please check the form.", "danger")
        return redirect(url_for("admin.manage_integrations"))

    # Check if name is being changed and if it conflicts with another integration
    new_name = form.name.data.strip()
    if new_name != integration.name:
        existing = TenantIntegration.query.filter_by(
            tenant_id=integration.tenant_id,
            name=new_name,
        ).first()
        if existing:
            flash(
                f"Integration name '{new_name}' already exists for this tenant.",
                "danger"
            )
            return redirect(url_for("admin.manage_integrations"))

    # Update the integration metadata
    integration.name = new_name
    integration.base_url = (form.base_url.data or "").strip() or None

    # Update API token if provided
    new_token = (form.api_token.data or "").strip()
    if new_token:
        integration.api_token = new_token

    db.session.commit()
    flash(f"Integration '{integration.name}' updated successfully.", "success")
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

                # Encrypt private key if provided
                if private_key_raw:
                    try:
                        from ..services.ssh_key_service import encrypt_private_key, SSHKeyServiceError
                        encrypted_key = encrypt_private_key(private_key_raw)
                        ssh_key.encrypted_private_key = encrypted_key
                    except SSHKeyServiceError as exc:
                        form.private_key.errors.append(
                            f"Failed to encrypt private key: {exc}"
                        )
                        return render_template(
                            "admin/ssh_keys.html",
                            form=form,
                            delete_form=delete_form,
                            ssh_keys=SSHKey.query.filter_by(user_id=current_user.model.id).order_by(SSHKey.created_at.desc()).all()
                        )

                db.session.add(ssh_key)
                try:
                    db.session.commit()
                    flash("SSH key added and encrypted successfully.", "success")
                    return redirect(url_for("admin.manage_ssh_keys"))
                except Exception as exc:
                    db.session.rollback()
                    current_app.logger.error("Failed to save SSH key: %s", exc)
                    form.private_key.errors.append("Failed to save SSH key to database.")

    keys = (
        SSHKey.query.filter_by(user_id=current_user.model.id)
        .order_by(SSHKey.created_at.desc())
        .all()
    )
    return render_template(
        "admin/ssh_keys.html", form=form, delete_form=delete_form, ssh_keys=keys
    )


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
            public_key_errors = cast(list[str], form.public_key.errors)
            public_key_errors.append(str(exc))
        else:
            existing = SSHKey.query.filter(
                SSHKey.fingerprint == fingerprint, SSHKey.id != ssh_key.id
            ).first()
            if existing:
                public_key_errors = cast(list[str], form.public_key.errors)
                public_key_errors.append(
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
                    current_app.logger.error(
                        "Failed to update SSH private key: %s", exc
                    )
                    if private_key_raw:
                        private_key_errors = cast(list[str], form.private_key.errors)
                        private_key_errors.append(
                            "Failed to store private key on disk."
                        )
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


@admin_bp.route("/user-identity-mappings", methods=["GET", "POST"])
@admin_required
def manage_user_identity_mappings():
    """Manage user identity mappings for external issue providers."""
    from ..services.user_identity_service import (
        UserIdentityError,
        update_identity_map,
    )

    form = UserIdentityMapForm()
    users = User.query.order_by(User.email).all()
    form.user_id.choices = [(user.id, f"{user.name} ({user.email})") for user in users]

    if form.validate_on_submit():
        try:
            update_identity_map(
                user_id=form.user_id.data,
                github_username=form.github_username.data or None,
                gitlab_username=form.gitlab_username.data or None,
                jira_account_id=form.jira_account_id.data or None,
            )
            db.session.commit()
            flash("User identity mapping saved successfully.", "success")
            return redirect(url_for("admin.manage_user_identity_mappings"))
        except UserIdentityError as exc:
            flash(str(exc), "danger")
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception("Failed to save user identity mapping.")
            flash(f"Error saving identity mapping: {exc}", "danger")
            db.session.rollback()

    # Load existing mappings
    identity_maps = UserIdentityMap.query.options(
        selectinload(UserIdentityMap.user)
    ).all()

    # Create delete forms for each mapping
    delete_forms = {
        mapping.user_id: UserIdentityMapDeleteForm(user_id=str(mapping.user_id))
        for mapping in identity_maps
    }

    return render_template(
        "admin/user_identity_mappings.html",
        form=form,
        identity_maps=identity_maps,
        delete_forms=delete_forms,
    )


@admin_bp.route("/user-identity-mappings/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user_identity_mapping(user_id: int):
    """Delete a user identity mapping."""
    from ..services.user_identity_service import delete_identity_map

    form = UserIdentityMapDeleteForm()
    if not form.validate_on_submit():
        flash("Invalid delete request.", "danger")
        return redirect(url_for("admin.manage_user_identity_mappings"))

    try:
        submitted_id = int(form.user_id.data)
    except (TypeError, ValueError):
        flash("Invalid user selection.", "warning")
        return redirect(url_for("admin.manage_user_identity_mappings"))

    if submitted_id != user_id:
        flash("Mismatched user identifier.", "warning")
        return redirect(url_for("admin.manage_user_identity_mappings"))

    try:
        if delete_identity_map(user_id):
            db.session.commit()
            flash("User identity mapping deleted.", "success")
        else:
            flash("User identity mapping not found.", "warning")
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Failed to delete user identity mapping.")
        flash(f"Error deleting identity mapping: {exc}", "danger")
        db.session.rollback()

    return redirect(url_for("admin.manage_user_identity_mappings"))


@admin_bp.route("/settings/global-agent-context", methods=["POST"])
@admin_required
def save_global_agent_context():
    """Save or update the global agent context."""
    from ..forms.admin import GlobalAgentContextForm
    from ..models import GlobalAgentContext

    form = GlobalAgentContextForm()
    if not form.validate_on_submit():
        flash("Invalid global agent context form submission.", "danger")
        return redirect(url_for("admin.manage_settings"))

    content = (form.content.data or "").strip()
    if not content:
        flash("Global agent context cannot be empty.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        # Check if global context already exists
        global_context = GlobalAgentContext.query.order_by(
            GlobalAgentContext.updated_at.desc()
        ).first()

        if global_context:
            # Update existing
            global_context.content = content
            global_context.updated_by_user_id = current_user.id
            global_context.updated_at = datetime.utcnow()
        else:
            # Create new
            global_context = GlobalAgentContext(
                content=content, updated_by_user_id=current_user.id
            )
            db.session.add(global_context)

        db.session.commit()
        flash("Global agent context saved successfully.", "success")

    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Failed to save global agent context.")
        flash(f"Error saving global agent context: {exc}", "danger")
        db.session.rollback()

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/global-agent-context/clear", methods=["POST"])
@admin_required
def clear_global_agent_context():
    """Clear the global agent context."""
    from ..forms.admin import GlobalAgentContextClearForm
    from ..models import GlobalAgentContext

    form = GlobalAgentContextClearForm()
    if not form.validate_on_submit():
        flash("Invalid clear request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        global_context = GlobalAgentContext.query.order_by(
            GlobalAgentContext.updated_at.desc()
        ).first()

        if global_context:
            db.session.delete(global_context)
            db.session.commit()
            flash(
                "Global agent context cleared. System will now use AGENTS.md from repository.",
                "success",
            )
        else:
            flash("No global agent context to clear.", "info")

    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Failed to clear global agent context.")
        flash(f"Error clearing global agent context: {exc}", "danger")
        db.session.rollback()

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/backups/create", methods=["POST"])
@admin_required
def create_backup_web():
    """Create a new database backup via the web interface."""
    form = BackupCreateForm()
    if not form.validate_on_submit():
        flash("Invalid backup creation request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        backup = create_backup(
            description=form.description.data,
            user_id=current_user.id,
        )
        flash(
            f"Backup created successfully: {backup.filename} ({backup.size_bytes} bytes)",
            "success",
        )
    except BackupError as exc:
        current_app.logger.exception("Failed to create backup.")
        flash(f"Error creating backup: {exc}", "danger")

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/backups/<int:backup_id>/restore", methods=["POST"])
@admin_required
def restore_backup_web(backup_id: int):
    """Restore database from a backup via the web interface."""
    form = BackupRestoreForm()
    if not form.validate_on_submit():
        flash("Invalid backup restore request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        backup = get_backup(backup_id)
        restore_backup(backup_id)
        flash(
            f"Database restored successfully from {backup.filename}. Please restart the application.",
            "success",
        )
    except BackupError as exc:
        current_app.logger.exception("Failed to restore backup.")
        flash(f"Error restoring backup: {exc}", "danger")

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/backups/<int:backup_id>/delete", methods=["POST"])
@admin_required
def delete_backup_web(backup_id: int):
    """Delete a backup via the web interface."""
    form = BackupDeleteForm()
    if not form.validate_on_submit():
        flash("Invalid backup deletion request.", "danger")
        return redirect(url_for("admin.manage_settings"))

    try:
        backup = get_backup(backup_id)
        # Delete the backup file and database record
        import os
        if os.path.exists(backup.filepath):
            os.remove(backup.filepath)
        db.session.delete(backup)
        db.session.commit()
        flash(f"Backup {backup.filename} deleted successfully.", "success")
    except BackupError as exc:
        current_app.logger.exception("Failed to delete backup.")
        flash(f"Error deleting backup: {exc}", "danger")
        db.session.rollback()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Failed to delete backup.")
        flash(f"Error deleting backup: {exc}", "danger")
        db.session.rollback()

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/backups/<int:backup_id>/download")
@admin_required
def download_backup_web(backup_id: int):
    """Download a backup file via the web interface."""
    try:
        backup = get_backup(backup_id)
        backup_path = Path(backup.filepath)

        return send_file(
            backup_path,
            as_attachment=True,
            download_name=backup.filename,
            mimetype="application/gzip",
        )
    except BackupError as exc:
        current_app.logger.exception("Failed to download backup.")
        flash(f"Error downloading backup: {exc}", "danger")
        return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/settings/yadm", methods=["POST"])
@admin_required
def save_yadm_settings():
    """Save global yadm (dotfiles) configuration."""
    from ..extensions import db
    from ..forms.admin import YadmSettingsForm
    from ..models import SystemConfig

    form = YadmSettingsForm()
    if form.validate_on_submit():
        try:
            # Save or update dotfile_repo_url
            repo_url_config = SystemConfig.query.filter_by(
                key="dotfile_repo_url"
            ).first()
            if not repo_url_config:
                repo_url_config = SystemConfig(key="dotfile_repo_url")
                db.session.add(repo_url_config)
            repo_url_config.value = {"url": form.dotfile_repo_url.data}

            # Save or update dotfile_repo_branch
            repo_branch_config = SystemConfig.query.filter_by(
                key="dotfile_repo_branch"
            ).first()
            if not repo_branch_config:
                repo_branch_config = SystemConfig(key="dotfile_repo_branch")
                db.session.add(repo_branch_config)
            repo_branch_config.value = {"branch": form.dotfile_repo_branch.data}

            # Save or update decrypt password (encrypted)
            if form.decrypt_password.data:
                from ..services.yadm_service import YadmKeyEncryption

                encrypted_password = YadmKeyEncryption.encrypt_gpg_key(
                    form.decrypt_password.data.encode()
                )
                decrypt_config = SystemConfig.query.filter_by(
                    key="dotfile_decrypt_password"
                ).first()
                if not decrypt_config:
                    decrypt_config = SystemConfig(key="dotfile_decrypt_password")
                    db.session.add(decrypt_config)
                decrypt_config.value = {"password": encrypted_password.decode()}
            else:
                # Clear password if empty
                decrypt_config = SystemConfig.query.filter_by(
                    key="dotfile_decrypt_password"
                ).first()
                if decrypt_config:
                    db.session.delete(decrypt_config)

            db.session.commit()
            flash(
                f"Dotfiles configuration saved: {form.dotfile_repo_url.data}",
                "success",
            )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("Failed to save yadm settings")
            flash(f"Error saving dotfiles configuration: {exc}", "danger")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{field}: {error}", "warning")

    return redirect(url_for("admin.manage_settings"))


@admin_bp.route("/yadm/init", methods=["POST"])
@admin_required
@login_required
def initialize_yadm_web():
    """Initialize yadm for the current user via web UI.

    Returns:
        JSON response with status, message, and paths
    """
    from ..models import Project
    from ..services.yadm_service import initialize_yadm_for_user, YadmServiceError

    try:
        # Use current_user
        user = current_user
        if not user:
            return jsonify({
                "status": "failed",
                "message": "User not authenticated"
            }), 401

        # Find dotfiles project for the user's tenant
        # Look across all tenants the user has projects in
        user_projects = Project.query.filter_by(owner_id=user.id).all()
        if not user_projects:
            return jsonify({
                "status": "failed",
                "message": "You have no associated projects"
            }), 400

        # Try to find a dotfiles project in any of the user's tenants
        dotfiles_project = None
        for proj in user_projects:
            dotfiles = Project.query.filter_by(
                name="dotfiles", tenant_id=proj.tenant_id
            ).first()
            if dotfiles:
                dotfiles_project = dotfiles
                break

        if not dotfiles_project:
            tenant_ids = [p.tenant_id for p in user_projects]
            return jsonify({
                "status": "failed",
                "message": "No dotfiles project found in any of your tenants"
            }), 400

        # Initialize yadm for the user
        result = initialize_yadm_for_user(
            user,
            repo_url=dotfiles_project.repo_url,
            repo_branch=dotfiles_project.default_branch or "main"
        )

        return jsonify(result), 200

    except YadmServiceError as exc:
        current_app.logger.warning(f"Yadm initialization failed for {current_user.email}: {exc}")
        return jsonify({
            "status": "failed",
            "message": str(exc)
        }), 400
    except Exception as exc:
        current_app.logger.exception(f"Unexpected error initializing yadm for {current_user.email}")
        return jsonify({
            "status": "failed",
            "message": f"Unexpected error: {exc}"
        }), 500


@admin_bp.route("/activity", methods=["GET"])
@admin_required
def view_activity():
    """View system activity log with filtering and pagination."""
    from ..models import Activity
    from ..services.activity_service import get_recent_activities

    # Get filter parameters
    limit_str = request.args.get("limit", "100")
    try:
        limit = min(int(limit_str), 1000)  # Max 1000 records
    except ValueError:
        limit = 100

    user_id_str = request.args.get("user_id")
    user_id = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
        except ValueError:
            pass

    action_type = request.args.get("action_type") or None
    resource_type = request.args.get("resource_type") or None
    status = request.args.get("status") or None
    source = request.args.get("source") or None

    # Fetch activities
    activities = get_recent_activities(
        limit=limit,
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        status=status,
        source=source,
    )

    # Get unique filter values for dropdowns
    all_action_types = (
        db.session.query(Activity.action_type)
        .distinct()
        .order_by(Activity.action_type)
        .all()
    )
    action_types = [a[0] for a in all_action_types if a[0]]

    all_resource_types = (
        db.session.query(Activity.resource_type)
        .distinct()
        .order_by(Activity.resource_type)
        .all()
    )
    resource_types = [r[0] for r in all_resource_types if r[0]]

    all_users = User.query.order_by(User.email).all()

    return render_template(
        "admin/activity.html",
        activities=activities,
        action_types=action_types,
        resource_types=resource_types,
        users=all_users,
        current_filters={
            "limit": limit,
            "user_id": user_id,
            "action_type": action_type,
            "resource_type": resource_type,
            "status": status,
            "source": source,
        },
    )


@admin_bp.route("/activity/export", methods=["GET"])
@admin_required
def export_activity():
    """Export activity log to CSV or JSON."""
    from ..services.activity_service import get_recent_activities
    import csv
    import io

    # Get same filter parameters as view
    limit_str = request.args.get("limit", "1000")
    try:
        limit = min(int(limit_str), 10000)  # Max 10000 for export
    except ValueError:
        limit = 1000

    user_id_str = request.args.get("user_id")
    user_id = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
        except ValueError:
            pass

    action_type = request.args.get("action_type") or None
    resource_type = request.args.get("resource_type") or None
    status = request.args.get("status") or None
    source = request.args.get("source") or None
    export_format = request.args.get("format", "csv")

    # Fetch activities
    activities = get_recent_activities(
        limit=limit,
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        status=status,
        source=source,
    )

    if export_format == "json":
        # Export as JSON
        import json
        from flask import Response

        activity_data = []
        for activity in activities:
            activity_dict = {
                "id": activity.id,
                "timestamp": activity.created_at.isoformat() if activity.created_at else None,
                "user_email": activity.user.email if activity.user else None,
                "action_type": activity.action_type,
                "resource_type": activity.resource_type,
                "resource_id": activity.resource_id,
                "resource_name": activity.resource_name,
                "status": activity.status,
                "description": activity.description,
                "extra_data": activity.extra_data,
                "error_message": activity.error_message,
                "ip_address": activity.ip_address,
                "source": activity.source,
            }
            activity_data.append(activity_dict)

        return Response(
            json.dumps(activity_data, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment;filename=activity_log.json"},
        )
    else:
        # Export as CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "ID",
            "Timestamp",
            "User",
            "Action Type",
            "Resource Type",
            "Resource ID",
            "Resource Name",
            "Status",
            "Description",
            "IP Address",
            "Source",
            "Error Message",
        ])

        # Write data
        for activity in activities:
            writer.writerow([
                activity.id,
                activity.created_at.isoformat() if activity.created_at else "",
                activity.user.email if activity.user else "",
                activity.action_type or "",
                activity.resource_type or "",
                activity.resource_id or "",
                activity.resource_name or "",
                activity.status or "",
                activity.description or "",
                activity.ip_address or "",
                activity.source or "",
                activity.error_message or "",
            ])

        response = cast(
            Any,
            current_app.response_class(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment;filename=activity_log.csv"},
            ),
        )
        return response


@admin_bp.route("/activity/cleanup", methods=["POST"])
@admin_required
def cleanup_activities():
    """Clean up old activity log entries."""
    from ..services.activity_cleanup import (
        ActivityCleanupError,
        cleanup_old_activities,
        get_cleanup_stats,
    )

    # Get parameters from form
    days_to_keep = request.form.get("days_to_keep", "90")
    max_records = request.form.get("max_records", "")
    dry_run = bool(request.form.get("dry_run"))

    try:
        days = int(days_to_keep)
        max_recs = int(max_records) if max_records else None

        # Get stats before cleanup
        stats_before = get_cleanup_stats()

        # Perform cleanup
        result = cleanup_old_activities(
            days_to_keep=days, max_records_to_keep=max_recs, dry_run=dry_run
        )

        if dry_run:
            flash(
                f"[DRY RUN] Would delete {result['deleted']} activities. "
                f"Total: {result['total_before']} → {result['total_after']}",
                "info",
            )
        else:
            flash(
                f"Successfully deleted {result['deleted']} old activities. "
                f"Total: {result['total_before']} → {result['total_after']}",
                "success",
            )

    except ValueError:
        flash("Invalid cleanup parameters.", "danger")
    except ActivityCleanupError as exc:
        flash(f"Cleanup failed: {exc}", "danger")
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Unexpected error during activity cleanup")
        flash(f"Unexpected error during cleanup: {exc}", "danger")

    return redirect(url_for("admin.view_activity"))


@admin_bp.route("/activity/stats", methods=["GET"])
@admin_required
def activity_stats():
    """Get activity log statistics (JSON endpoint)."""
    from ..services.activity_cleanup import get_cleanup_stats

    try:
        stats = get_cleanup_stats()
        # Convert datetime objects to strings for JSON serialization
        if stats["oldest_activity"]:
            stats["oldest_activity"] = stats["oldest_activity"].isoformat()
        if stats["newest_activity"]:
            stats["newest_activity"] = stats["newest_activity"].isoformat()

        return jsonify({"ok": True, "stats": stats})
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Failed to get activity stats")
        return jsonify({"ok": False, "error": str(exc)}), 500


@admin_bp.route("/activity/list", methods=["GET"])
@admin_required
def activity_list_api():
    """List activities via API (for CLI)."""
    from ..services.activity_service import get_recent_activities

    # Get filter parameters (same as view_activity)
    limit_str = request.args.get("limit", "50")
    try:
        limit = min(int(limit_str), 1000)
    except ValueError:
        limit = 50

    user_id_str = request.args.get("user_id")
    user_id = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
        except ValueError:
            pass

    action_type = request.args.get("action_type") or None
    resource_type = request.args.get("resource_type") or None
    status = request.args.get("status") or None
    source = request.args.get("source") or None

    # Fetch activities
    activities = get_recent_activities(
        limit=limit,
        user_id=user_id,
        action_type=action_type,
        resource_type=resource_type,
        status=status,
        source=source,
    )

    # Convert to JSON
    activity_list = []
    for activity in activities:
        activity_dict = {
            "id": activity.id,
            "timestamp": activity.created_at.isoformat() if activity.created_at else None,
            "user_id": activity.user_id,
            "user_email": activity.user.email if activity.user else None,
            "action_type": activity.action_type,
            "resource_type": activity.resource_type,
            "resource_id": activity.resource_id,
            "resource_name": activity.resource_name,
            "status": activity.status,
            "description": activity.description,
            "extra_data": activity.extra_data,
            "error_message": activity.error_message,
            "ip_address": activity.ip_address,
            "source": activity.source,
        }
        activity_list.append(activity_dict)

    return jsonify({"ok": True, "count": len(activity_list), "activities": activity_list})


@admin_bp.route("/statistics", methods=["GET"])
@login_required
def view_statistics():
    """View issue resolution statistics and workflow metrics."""
    from ..services.statistics_service import (
        get_contributor_statistics,
        get_project_list,
        get_resolution_statistics,
        get_workflow_statistics,
    )

    # Get filter parameters
    project_id_str = request.args.get("project_id")
    days_str = request.args.get("days", "30")

    project_id = None
    if project_id_str:
        try:
            project_id = int(project_id_str)
        except ValueError:
            pass

    try:
        days = int(days_str)
        days = max(1, min(days, 365))  # Limit to 1-365 days
    except ValueError:
        days = 30

    # Get tenant_id for filtering
    tenant_id = None
    if not current_user.is_admin:
        # Non-admin users see only their tenant's data
        user_projects = Project.query.filter_by(owner_id=current_user.id).first()
        if user_projects:
            tenant_id = user_projects.tenant_id

    # Fetch statistics
    try:
        resolution_stats = get_resolution_statistics(
            tenant_id=tenant_id, project_id=project_id, days=days
        )
        workflow_stats = get_workflow_statistics(
            tenant_id=tenant_id, project_id=project_id
        )
        contributor_stats = get_contributor_statistics(
            tenant_id=tenant_id, project_id=project_id, days=days
        )
        project_list = get_project_list(tenant_id=tenant_id)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Failed to fetch statistics")
        flash("Error loading statistics.", "danger")
        resolution_stats = {
            "total_resolved": 0,
            "avg_resolution_time_hours": 0,
            "project_breakdown": {},
            "period_days": days,
        }
        workflow_stats = {
            "total_issues": 0,
            "open_count": 0,
            "closed_count": 0,
            "other_count": 0,
            "status_distribution": {},
        }
        contributor_stats = []
        project_list = []

    return render_template(
        "admin/statistics.html",
        resolution_stats=resolution_stats,
        workflow_stats=workflow_stats,
        contributor_stats=contributor_stats,
        project_list=project_list,
        selected_project_id=project_id,
        selected_days=days,
    )
