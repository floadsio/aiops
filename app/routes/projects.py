from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask_login import current_user, login_required  # type: ignore
from sqlalchemy.orm import selectinload

from ..ai_sessions import (
    close_session,
    create_session,
    get_session,
    resize_session,
    stream_session,
    write_to_session,
)
from ..extensions import db
from ..forms.project import (
    AgentFileForm,
    AIRunForm,
    AnsibleForm,
    GitActionForm,
    IssueCreateForm,
    ProjectKeyForm,
)
from ..models import AISession, ExternalIssue, Project, ProjectIntegration, SSHKey
from ..services.agent_context import write_tracked_issue_context
from ..services.ansible_runner import (
    SemaphoreAPIError,
    SemaphoreConfigError,
    SemaphoreTimeoutError,
    get_semaphore_templates,
    run_ansible_playbook,
)
from ..services.ai_status_service import AIStatusError, get_claude_status
from ..services.git_service import (
    commit_project_files,
    get_project_commit_history,
    get_repo_status,
    run_git_action,
)
from ..services.issues import (
    ASSIGN_PROVIDER_REGISTRY,
    CREATE_PROVIDER_REGISTRY,
    IssueSyncError,
    assign_issue_for_project_integration,
    close_issue_for_project_integration,
    create_issue_for_project_integration,
    serialize_issue_comments,
    sync_project_integration,
)
from ..services.issues.utils import normalize_issue_status
from ..services.tmux_service import (
    TmuxServiceError,
    close_tmux_target,
    get_or_create_window_for_project,
    list_windows_for_aliases,
    session_name_for_user,
)

ChoiceItem = tuple[Any, str] | tuple[Any, str, dict[str, Any]]
ChoiceList = list[ChoiceItem]

projects_bp = Blueprint("projects", __name__, template_folder="../templates/projects")

AGENTS_OVERRIDE_FILENAME = "AGENTS.override.md"
AGENTS_DEFAULT_COMMIT_MESSAGE = f"Update {AGENTS_OVERRIDE_FILENAME}"


def _authorize(project: Project) -> bool:
    if current_user.is_admin:
        return True
    return project.owner_id == current_user.model.id


def _current_tmux_session_name() -> str:
    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    return session_name_for_user(user_obj)


def _current_linux_username() -> str | None:
    """Get the Linux username for the current user."""
    from ..services.linux_users import resolve_linux_username

    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    if user_obj is None:
        return None
    return resolve_linux_username(user_obj)


def _current_user_obj():
    """Get the current user object for workspace operations."""
    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    return user_obj


@projects_bp.route("/ai/status", methods=["GET"])
@login_required
def ai_status_overview():
    """Display per-user AI tool capacity information."""
    user = _current_user_obj()
    if user is None:
        abort(403)

    # Display Claude usage from database instead of running CLI command
    # The usage data is populated by the update mechanism or API calls
    claude_usage = {
        "input_tokens_limit": user.claude_input_tokens_limit,
        "input_tokens_remaining": user.claude_input_tokens_remaining,
        "output_tokens_limit": user.claude_output_tokens_limit,
        "output_tokens_remaining": user.claude_output_tokens_remaining,
        "requests_limit": user.claude_requests_limit,
        "requests_remaining": user.claude_requests_remaining,
        "last_updated": user.claude_usage_last_updated,
    }

    # Skip Claude CLI status check for now - it times out when Claude sessions are active
    # TODO: Implement non-blocking status check or use a background job
    claude_status = None
    claude_status_error = "Claude CLI status check is temporarily disabled to avoid timeouts during active sessions."

    return render_template(
        "projects/ai_status.html",
        claude_usage=claude_usage,
        claude_status=claude_status,
        claude_status_error=claude_status_error,
        linux_username=_current_linux_username(),
    )


def _issue_sort_key(issue: ExternalIssue):
    reference = issue.external_updated_at or issue.updated_at or issue.created_at
    if reference is None:
        reference = datetime.min.replace(tzinfo=timezone.utc)
    elif reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference


@projects_bp.route("/<int:project_id>", methods=["GET", "POST"])
@login_required
def project_detail(project_id: int):
    project = (
        Project.query.options(
            selectinload(Project.issue_integrations).selectinload(
                ProjectIntegration.integration
            ),
            selectinload(Project.issue_integrations).selectinload(
                ProjectIntegration.issues
            ),
        )
        .filter_by(id=project_id)
        .first()
    )
    if project is None:
        abort(404)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    git_form = GitActionForm(prefix="git")
    ssh_key_form = ProjectKeyForm(prefix="sshkey")

    tenant_keys = list(project.tenant.ssh_keys) if project.tenant else []
    key_choices: ChoiceList = [(0, "Use tenant default")]
    tenant_default_key = None
    for key in tenant_keys:
        if tenant_default_key is None and key.private_key_path:
            tenant_default_key = key
        label = key.name
        if key.fingerprint:
            label = f"{label} ({key.fingerprint[:12]})"
        key_choices.append((key.id, label))
    ssh_key_form.ssh_key_id.choices = key_choices
    if not ssh_key_form.is_submitted():
        ssh_key_form.ssh_key_id.data = project.ssh_key_id or 0
    link_by_id = {link.id: link for link in project.issue_integrations}
    supported_providers = set(CREATE_PROVIDER_REGISTRY.keys())

    # Get all users for assignee dropdown
    from ..models import User

    all_users = User.query.order_by(User.name).all()
    user_choices = [(0, "— No Assignee —")] + [
        (user.id, f"{user.name} ({user.email})") for user in all_users
    ]

    issue_create_forms: dict[int, IssueCreateForm] = {}
    for link in project.issue_integrations:
        integration = link.integration
        provider_key = (
            (integration.provider or "").lower()
            if integration and integration.provider
            else ""
        )
        if integration and integration.enabled and provider_key in supported_providers:
            form = IssueCreateForm(prefix=f"create-{link.id}")
            form.integration_id.data = str(link.id)
            form.assignee_user_id.choices = user_choices
            if not form.is_submitted():
                default_issue_type = (link.config or {}).get("issue_type")
                if default_issue_type:
                    form.issue_type.data = default_issue_type
            issue_create_forms[link.id] = form

    message = None
    error = None

    if ssh_key_form.submit.data and ssh_key_form.validate_on_submit():
        selected_id = ssh_key_form.ssh_key_id.data or 0
        selected_key: SSHKey | None = None
        if selected_id:
            selected_key = SSHKey.query.get(selected_id)
            if selected_key is None or selected_key.tenant_id != project.tenant_id:
                flash("Invalid SSH key selection for this project.", "danger")
                return redirect(
                    url_for("projects.project_detail", project_id=project.id)
                )
        project.ssh_key = selected_key
        db.session.commit()
        if selected_key is None:
            flash("Project will use the tenant default SSH key.", "success")
        else:
            flash(f"Project SSH key updated to {selected_key.name}.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))
    elif ssh_key_form.submit.data:
        flash(
            "Unable to update project SSH key. Please review the selection.", "danger"
        )
    elif git_form.submit.data and git_form.validate_on_submit():
        try:
            message = run_git_action(
                project,
                git_form.action.data,
                git_form.ref.data or None,
                user=_current_user_obj(),
                clean=bool(git_form.clean_pull.data),
            )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    elif request.method == "POST":
        for link_id, form in issue_create_forms.items():
            if not form.submit.data:
                continue
            if form.validate_on_submit():
                try:
                    submitted_id = int(form.integration_id.data)
                except (TypeError, ValueError):
                    flash("Invalid integration target for issue creation.", "danger")
                    break

                link = link_by_id.get(submitted_id)
                if link is None:
                    flash("Project integration not found.", "danger")
                    break

                summary = (form.summary.data or "").strip()
                description = (form.description.data or "").strip() or None
                issue_type_value = (form.issue_type.data or "").strip() or None
                labels_raw = form.labels.data or ""
                labels = [
                    label.strip() for label in labels_raw.split(",") if label.strip()
                ]
                assignee_user_id = form.assignee_user_id.data or None
                if assignee_user_id == 0:
                    assignee_user_id = None

                try:
                    payload = create_issue_for_project_integration(
                        link,
                        summary=summary,
                        description=description,
                        issue_type=issue_type_value,
                        labels=labels or None,
                        assignee_user_id=assignee_user_id,
                    )
                    sync_project_integration(link)
                    db.session.commit()
                except IssueSyncError as exc:
                    db.session.rollback()
                    flash(f"Failed to create issue: {exc}", "danger")
                except Exception:  # noqa: BLE001
                    db.session.rollback()
                    current_app.logger.exception(
                        "Issue creation failed for project_id=%s integration_id=%s",
                        project.id,
                        submitted_id,
                    )
                    flash("Unexpected error while creating the issue.", "danger")
                else:
                    integration = link.integration
                    provider_display = (
                        (
                            integration.name
                            or (integration.provider or "Integration").title()
                        )
                        if integration
                        else "Integration"
                    )
                    flash(
                        f"Created issue {payload.external_id} via {provider_display}.",
                        "success",
                    )
                    return redirect(
                        url_for("projects.project_detail", project_id=project.id)
                    )
            else:
                flash("Please correct the errors in the issue form.", "danger")
            break

    status = get_repo_status(project, user=_current_user_obj())

    # Get workspace status for current user
    from ..services.workspace_service import get_workspace_status

    workspace_status = get_workspace_status(project, _current_user_obj())

    ai_tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    default_ai_shell = current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    codex_command = ai_tool_commands.get("codex", default_ai_shell)

    def _format_timestamp(value):
        if value is None:
            return None
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone().strftime("%b %d, %Y • %H:%M %Z")

    def _parse_comment_timestamp(raw_value):
        if raw_value is None:
            return None
        if isinstance(raw_value, datetime):
            if raw_value.tzinfo is None:
                return raw_value.replace(tzinfo=timezone.utc)
            return raw_value.astimezone(timezone.utc)
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return None
            normalized = text.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return None

    def _prepare_comment_entries(raw_comments: list[dict[str, object]] | None):
        entries: list[dict[str, object]] = []
        if not raw_comments:
            return entries
        for comment in raw_comments:
            if not isinstance(comment, dict):
                continue
            created_display = None
            created_value = _parse_comment_timestamp(comment.get("created_at"))
            if created_value:
                created_display = _format_timestamp(created_value)
            entries.append(
                {
                    "author": comment.get("author"),
                    "body": comment.get("body") or "",
                    "created_display": created_display,
                    "url": comment.get("url"),
                }
            )
        return entries

    issue_groups: list[dict[str, object]] = []
    total_issue_count = 0
    all_project_issues = [
        issue for link in project.issue_integrations for issue in link.issues
    ]

    from ..models import PinnedIssue

    pinned_issue_ids = {
        pinned.issue_id
        for pinned in PinnedIssue.query.filter_by(user_id=_current_user_obj().id).all()
    }

    status_counts: Counter[str] = Counter()
    status_labels: dict[str, str] = {}
    for issue in all_project_issues:
        status_key, status_label = normalize_issue_status(issue.status)
        status_counts[status_key] += 1
        status_labels.setdefault(status_key, status_label)

    total_issue_full_count = len(all_project_issues)

    raw_filter = (request.args.get("issue_status") or "").strip().lower()
    has_open_issues = status_counts.get("open", 0) > 0
    default_filter = "open" if has_open_issues else "all"
    if raw_filter == "all":
        issue_status_filter = "all"
    elif raw_filter in status_labels:
        issue_status_filter = raw_filter
    elif raw_filter == "__none__" and "__none__" in status_labels:
        issue_status_filter = "__none__"
    else:
        issue_status_filter = default_filter
    if (
        issue_status_filter == "open"
        and status_counts.get("open", 0) == 0
        and total_issue_full_count
    ):
        issue_status_filter = "all"

    def _issue_matches_filter(issue: ExternalIssue) -> bool:
        if issue_status_filter == "all":
            return True
        issue_status_key, _ = normalize_issue_status(issue.status)
        return issue_status_key == issue_status_filter

    issue_status_filter_label = (
        "All statuses"
        if issue_status_filter == "all"
        else status_labels.get(issue_status_filter, issue_status_filter.title())
    )

    def _status_option_sort_key(item: tuple[str, str]) -> tuple[int, str]:
        key, label = item
        priority = 0 if key == "open" else 1
        return priority, label.lower()

    issue_status_options = [
        {"value": "all", "label": "All statuses", "count": total_issue_full_count}
    ]
    sorted_status_items = sorted(status_labels.items(), key=_status_option_sort_key)
    for status_key, status_label in sorted_status_items:
        issue_status_options.append(
            {
                "value": status_key,
                "label": status_label,
                "count": status_counts.get(status_key, 0),
            }
        )

    for link in project.issue_integrations:
        integration = link.integration
        sorted_issues = sorted(link.issues, key=_issue_sort_key, reverse=True)
        issue_entries: list[dict[str, object]] = []
        for record in sorted_issues:
            if not _issue_matches_filter(record):
                continue
            updated_display = _format_timestamp(
                record.external_updated_at or record.updated_at or record.created_at
            )
            status_key, _ = normalize_issue_status(record.status)
            provider_key_lower = (
                (integration.provider or "").lower()
                if integration and integration.provider
                else ""
            )
            issue_payload = {
                "id": record.id,
                "external_id": record.external_id,
                "title": record.title,
                "status": record.status,
                "assignee": record.assignee,
                "url": record.url,
                "labels": record.labels or [],
                "updated_display": updated_display,
                "status_key": status_key,
                "can_assign": provider_key_lower in ASSIGN_PROVIDER_REGISTRY,
                "is_pinned": record.id in pinned_issue_ids,
            }
            comments = _prepare_comment_entries(getattr(record, "comments", []))
            issue_payload["comments"] = comments
            issue_payload["comment_count"] = len(comments)
            issue_entries.append(
                {
                    **issue_payload,
                    "codex_payload": {
                        "prompt": "",
                        "tool": "codex",
                        "command": codex_command,
                        "autoStart": True,
                        "issueId": record.id,
                        "agentPath": None,
                        "tmuxTarget": None,
                    },
                }
            )
        total_issue_count += len(issue_entries)
        provider_key = integration.provider if integration else "unknown"
        provider_display = provider_key.capitalize() if provider_key else "Unknown"
        issue_groups.append(
            {
                "integration_name": integration.name
                if integration
                else "Unknown Integration",
                "provider": provider_key,
                "provider_display": provider_display,
                "enabled": integration.enabled if integration else False,
                "project_identifier": link.external_identifier,
                "last_synced": _format_timestamp(link.last_synced_at),
                "issues": issue_entries,
                "total_issues": len(sorted_issues),
                "create_form": issue_create_forms.get(link.id),
                "can_create_issue": link.id in issue_create_forms,
            }
        )

    commit_history: list[dict[str, str]] = []
    commit_history_error: str | None = None
    try:
        raw_history = get_project_commit_history(project, limit=8)
        for entry in raw_history:
            commit_history.append(
                {
                    "short_hash": entry["short_hash"],
                    "message": entry["message"],
                    "author": entry["author"],
                    "date_display": _format_timestamp(entry["date"]),
                }
            )
    except Exception as exc:  # noqa: BLE001
        commit_history_error = str(exc)

    return render_template(
        "projects/detail.html",
        project=project,
        git_form=git_form,
        status=status,
        workspace_status=workspace_status,
        message=message,
        error=error,
        issue_groups=issue_groups,
        total_issue_count=total_issue_count,
        total_issue_full_count=total_issue_full_count,
        issue_status_filter=issue_status_filter,
        issue_status_filter_label=issue_status_filter_label,
        issue_status_options=issue_status_options,
        ssh_key_form=ssh_key_form,
        tenant_default_key=tenant_default_key,
        commit_history=commit_history,
        commit_history_error=commit_history_error,
        ai_tool_commands=ai_tool_commands,
        default_ai_shell=default_ai_shell,
    )


def _format_agents_timestamp(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    timestamp = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return timestamp.astimezone().strftime("%b %d, %Y • %H:%M %Z")


@projects_bp.route("/<int:project_id>/agents", methods=["GET", "POST"])
@login_required
def edit_agents_file(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    agents_path = Path(project.local_path).expanduser() / AGENTS_OVERRIDE_FILENAME
    form = AgentFileForm()

    if request.method == "GET":
        if not form.contents.data:
            try:
                form.contents.data = agents_path.read_text(encoding="utf-8")
            except OSError:
                form.contents.data = ""
        if not form.commit_message.data:
            form.commit_message.data = AGENTS_DEFAULT_COMMIT_MESSAGE

    if form.validate_on_submit():
        content = form.contents.data or ""
        try:
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            content_errors = cast(list[str], form.contents.errors)
            content_errors.append(f"Failed to write {AGENTS_OVERRIDE_FILENAME}: {exc}")
        else:
            flash(
                f"Saved {AGENTS_OVERRIDE_FILENAME} to the local workspace.", "success"
            )
            if form.save_and_push.data:
                commit_message = (form.commit_message.data or "").strip()
                if not commit_message:
                    commit_errors = cast(list[str], form.commit_message.errors)
                    commit_errors.append("Commit message is required to push changes.")
                else:
                    try:
                        committed = commit_project_files(
                            project, [agents_path], commit_message
                        )
                    except RuntimeError as exc:
                        flash(f"Commit failed: {exc}", "danger")
                    else:
                        if not committed:
                            flash("No changes to commit.", "warning")
                        else:
                            try:
                                push_output = run_git_action(
                                    project, "push", user=_current_user_obj()
                                )
                            except RuntimeError as exc:
                                flash(f"Push failed: {exc}", "danger")
                            else:
                                flash(
                                    f"Committed and pushed {AGENTS_OVERRIDE_FILENAME}.",
                                    "success",
                                )
                                if push_output:
                                    flash(push_output, "info")
            if not form.errors:
                return redirect(
                    url_for("projects.edit_agents_file", project_id=project.id)
                )

    file_exists = agents_path.exists()
    last_modified_display = _format_agents_timestamp(
        agents_path if file_exists else None
    )
    relative_path = AGENTS_OVERRIDE_FILENAME
    try:
        relative_path = str(agents_path.relative_to(Path(project.local_path)))
    except (ValueError, OSError):
        relative_path = AGENTS_OVERRIDE_FILENAME

    return render_template(
        "projects/agents.html",
        project=project,
        form=form,
        file_exists=file_exists,
        relative_path=relative_path,
        last_modified_display=last_modified_display,
    )


@projects_bp.route("/<int:project_id>/ai", methods=["GET"])
@login_required
def project_ai_console(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))
    tmux_session_name = _current_tmux_session_name()

    # Check if issue_id is provided and populate AGENTS.override.md
    issue_id_param = request.args.get("issue_id")
    if issue_id_param:
        try:
            issue_id = int(issue_id_param)
            issue = ExternalIssue.query.get(issue_id)
            if (
                issue
                and issue.project_integration
                and issue.project_integration.project_id == project_id
            ):
                # Populate AGENTS.override.md for this issue
                from ..services.agent_context import write_tracked_issue_context

                all_issues = sorted(
                    ExternalIssue.query.join(ProjectIntegration)
                    .filter(ProjectIntegration.project_id == project_id)
                    .all(),
                    key=_issue_sort_key,
                    reverse=True,
                )
                try:
                    write_tracked_issue_context(
                        project,
                        issue,
                        all_issues,
                        identity_user=getattr(current_user, "model", None),
                    )
                    flash(
                        f"Issue context prepared: {issue.title} (#{issue.external_id})",
                        "success",
                    )
                except OSError as exc:
                    current_app.logger.exception(
                        "Failed to update agent context for project %s", project.id
                    )
                    flash(f"Failed to prepare issue context: {exc}", "danger")
        except (ValueError, TypeError):
            pass  # Invalid issue_id, ignore

    form = AIRunForm()
    allowed_tools = current_app.config["ALLOWED_AI_TOOLS"]
    preferred_order = ["claude", "codex", "gemini", "aider", "shell"]
    ordered_keys: list[str] = [key for key in preferred_order if key in allowed_tools]
    ordered_keys.extend(key for key in allowed_tools if key not in ordered_keys)
    tool_choices: list[tuple[str, str]] = [
        (key, key.capitalize()) for key in ordered_keys
    ]
    form.ai_tool.choices = tool_choices  # type: ignore[assignment]
    default_tool = current_app.config.get("DEFAULT_AI_TOOL", "claude")
    if default_tool in current_app.config["ALLOWED_AI_TOOLS"]:
        form.ai_tool.data = default_tool

    tmux_windows: list = []
    tmux_error: str | None = None
    tenant = project.tenant
    tenant_name = tenant.name if tenant else ""
    linux_username = _current_linux_username()
    try:
        # Ensure a window exists for this project so users can attach immediately
        project_window = get_or_create_window_for_project(
            project, session_name=tmux_session_name, linux_username=linux_username
        )
        created_display = (
            project_window.created.astimezone().strftime("%b %d, %Y • %H:%M %Z")
            if project_window.created
            else None
        )
        tmux_windows.append(
            {
                "session": project_window.session_name,
                "window": project_window.window_name,
                "target": project_window.target,
                "panes": project_window.panes,
                "created": project_window.created,
                "created_display": created_display,
            }
        )

        extra_windows = list_windows_for_aliases(
            tenant_name,
            project_local_path=project.local_path,
            extra_aliases=(project.name, getattr(project, "slug", None)),
            session_name=tmux_session_name,
            linux_username=linux_username,
        )
        for window in extra_windows:
            if window.target == project_window.target:
                continue
            created_display = (
                window.created.astimezone().strftime("%b %d, %Y • %H:%M %Z")
                if window.created
                else None
            )
            tmux_windows.append(
                {
                    "session": window.session_name,
                    "window": window.window_name,
                    "target": window.target,
                    "panes": window.panes,
                    "created": window.created,
                    "created_display": created_display,
                }
            )
    except TmuxServiceError as exc:
        tmux_error = str(exc)

    requested_target = request.args.get("attach") or request.args.get("tmux_target")

    default_codex_command = current_app.config["ALLOWED_AI_TOOLS"].get(
        default_tool, current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    )

    ai_tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})

    # Get the workspace path for the current user
    from ..services.workspace_service import get_workspace_path

    user_obj = getattr(current_user, "model", None)
    if user_obj is None and getattr(current_user, "is_authenticated", False):
        user_obj = current_user
    workspace_path = get_workspace_path(project, user_obj) if user_obj else None
    local_path = str(workspace_path) if workspace_path else project.local_path

    return render_template(
        "projects/ai_console.html",
        project=project,
        form=form,
        tmux_windows=tmux_windows,
        tmux_error=tmux_error,
        requested_tmux_target=requested_target,
        default_codex_command=default_codex_command,
        ai_tool_commands=ai_tool_commands,
        local_path=local_path,
    )


@projects_bp.route("/<int:project_id>/issues/<int:issue_id>/prepare", methods=["POST"])
@login_required
def prepare_issue_context(project_id: int, issue_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        return jsonify({"error": "Access denied"}), 403

    issue = ExternalIssue.query.get_or_404(issue_id)
    if (
        issue.project_integration is None
        or issue.project_integration.project_id != project_id
    ):
        abort(404)

    request_payload = request.get_json(silent=True) or {}

    all_issues = sorted(
        ExternalIssue.query.join(ProjectIntegration)
        .filter(ProjectIntegration.project_id == project_id)
        .all(),
        key=_issue_sort_key,
        reverse=True,
    )

    prompt = ""
    agents_path = None
    try:
        agents_path = write_tracked_issue_context(
            project,
            issue,
            all_issues,
            identity_user=getattr(current_user, "model", None),
        )
    except OSError as exc:
        current_app.logger.exception(
            "Failed to update agent context for project %s", project.id
        )
        return jsonify({"error": f"Failed to write agent files: {exc}"}), 500

    requested_tool_raw = request_payload.get("tool")
    requested_tool = (
        str(requested_tool_raw).strip().lower() if requested_tool_raw else ""
    )
    ai_tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    default_ai_shell = current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    configured_default_tool_raw = current_app.config.get("DEFAULT_AI_TOOL", "")
    configured_default_tool = (
        str(configured_default_tool_raw).strip().lower()
        if configured_default_tool_raw
        else ""
    )

    selected_tool: str | None = None
    if requested_tool and requested_tool in ai_tool_commands:
        selected_tool = requested_tool
    elif "codex" in ai_tool_commands:
        selected_tool = "codex"
    elif configured_default_tool and configured_default_tool in ai_tool_commands:
        selected_tool = configured_default_tool
    elif ai_tool_commands:
        selected_tool = next(iter(ai_tool_commands))

    command = (
        ai_tool_commands.get(selected_tool, default_ai_shell)
        if selected_tool
        else default_ai_shell
    )

    tmux_session_name = _current_tmux_session_name()
    linux_username = _current_linux_username()

    return jsonify(
        {
            "prompt": prompt,
            "command": command,
            "tool": selected_tool or "",
            "agent_path": str(agents_path) if agents_path else None,
            "tmux_target": get_or_create_window_for_project(
                project,
                session_name=tmux_session_name,
                linux_username=linux_username,
            ).target,
        }
    )


@projects_bp.route(
    "/<int:project_id>/issues/<int:issue_id>/populate-agent-md", methods=["POST"]
)
@login_required
def populate_issue_agents_md(project_id: int, issue_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        return jsonify({"error": "Access denied"}), 403

    issue = ExternalIssue.query.get_or_404(issue_id)
    if (
        issue.project_integration is None
        or issue.project_integration.project_id != project_id
    ):
        abort(404)

    all_issues = sorted(
        ExternalIssue.query.join(ProjectIntegration)
        .filter(ProjectIntegration.project_id == project_id)
        .all(),
        key=_issue_sort_key,
        reverse=True,
    )

    try:
        tracked_path = write_tracked_issue_context(
            project,
            issue,
            all_issues,
            identity_user=getattr(current_user, "model", None),
        )
    except OSError as exc:
        current_app.logger.exception(
            "Failed to populate agent context for project %s", project.id
        )
        return jsonify({"error": f"Failed to write agent files: {exc}"}), 500

    return jsonify(
        {
            "message": "Updated agent context files.",
            "tracked_path": str(tracked_path),
            "local_path": str(tracked_path),
        }
    )


@projects_bp.route("/<int:project_id>/issues/<int:issue_id>/assign", methods=["POST"])
@login_required
def assign_issue(project_id: int, issue_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    issue = ExternalIssue.query.get_or_404(issue_id)
    integration = issue.project_integration
    if integration is None or integration.project_id != project_id:
        abort(404)

    assignee_input = (request.form.get("assignee") or "").strip()
    assignees = [value.strip() for value in assignee_input.split(",") if value.strip()]
    if not assignees:
        flash("Provide at least one assignee.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    try:
        payload = assign_issue_for_project_integration(
            integration, issue.external_id, assignees
        )
    except IssueSyncError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    issue.title = payload.title or issue.title
    issue.status = payload.status
    issue.assignee = payload.assignee
    issue.url = payload.url
    issue.labels = payload.labels
    issue.external_updated_at = payload.external_updated_at
    issue.last_seen_at = datetime.now(timezone.utc)
    issue.raw_payload = payload.raw
    issue.comments = serialize_issue_comments(payload.comments)
    db.session.commit()

    assignee_display = payload.assignee or ", ".join(assignees)
    flash(f"Assigned issue {issue.external_id} to {assignee_display}.", "success")
    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/issues/<int:issue_id>/close", methods=["POST"])
@login_required
def close_issue(project_id: int, issue_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    issue = ExternalIssue.query.get_or_404(issue_id)
    integration = issue.project_integration
    if integration is None or integration.project_id != project_id:
        abort(404)

    try:
        payload = close_issue_for_project_integration(integration, issue.external_id)
    except IssueSyncError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    issue.title = payload.title or issue.title
    issue.status = payload.status
    issue.assignee = payload.assignee
    issue.url = payload.url
    issue.labels = payload.labels
    issue.external_updated_at = payload.external_updated_at
    issue.last_seen_at = datetime.now(timezone.utc)
    issue.raw_payload = payload.raw
    issue.comments = serialize_issue_comments(payload.comments)
    db.session.commit()

    flash(f"Closed issue {issue.external_id}.", "success")
    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/issues/<int:issue_id>/pin", methods=["POST"])
@login_required
def pin_issue(project_id: int, issue_id: int):
    from ..models import PinnedIssue

    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    issue = ExternalIssue.query.get_or_404(issue_id)
    integration = issue.project_integration
    if integration is None or integration.project_id != project_id:
        abort(404)

    existing = PinnedIssue.query.filter_by(
        user_id=current_user.model.id, issue_id=issue_id
    ).first()

    if not existing:
        pinned = PinnedIssue(user_id=current_user.model.id, issue_id=issue_id)
        db.session.add(pinned)
        db.session.commit()
        flash(f"Pinned issue: {issue.title}", "success")
    else:
        flash("Issue is already pinned.", "info")

    # Redirect to the next URL if provided, otherwise back to project detail
    next_url = request.args.get("next") or request.form.get("next")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/issues/<int:issue_id>/unpin", methods=["POST"])
@login_required
def unpin_issue(project_id: int, issue_id: int):
    from ..models import PinnedIssue

    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    issue = ExternalIssue.query.get_or_404(issue_id)
    integration = issue.project_integration
    if integration is None or integration.project_id != project_id:
        abort(404)

    pinned = PinnedIssue.query.filter_by(
        user_id=current_user.model.id, issue_id=issue_id
    ).first()

    if pinned:
        db.session.delete(pinned)
        db.session.commit()
        flash(f"Unpinned issue: {issue.title}", "success")
    else:
        flash("Issue is not pinned.", "info")

    # Redirect to the next URL if provided, otherwise back to project detail
    next_url = request.args.get("next") or request.form.get("next")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("projects.project_detail", project_id=project.id))


@projects_bp.route("/<int:project_id>/ai/session", methods=["POST"])
@login_required
def start_ai_session(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        return jsonify({"error": "Access denied"}), 403

    payload = request.get_json(silent=True) or {}
    tool = payload.get("tool") or None
    prompt = payload.get("prompt", "")
    command = payload.get("command") or None
    rows = payload.get("rows")
    cols = payload.get("cols")
    tmux_target = (payload.get("tmux_target") or "").strip() or None
    issue_id = payload.get("issue_id") or None

    rows = rows if isinstance(rows, int) and rows > 0 else None
    cols = cols if isinstance(cols, int) and cols > 0 else None
    tmux_session_name = _current_tmux_session_name()

    try:
        session = create_session(
            project,
            current_user.model.id,
            tool=tool,
            command=command,
            rows=rows,
            cols=cols,
            tmux_target=tmux_target,
            tmux_session_name=tmux_session_name,
            issue_id=issue_id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if prompt.strip():
        write_to_session(session, prompt + "\n")

    return jsonify({"session_id": session.id})


def _get_authorized_session(project_id: int, session_id: str):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        abort(403)
    session = get_session(session_id)
    if session is None or session.project_id != project_id:
        abort(404)
    return session


@projects_bp.route("/<int:project_id>/ai/session/<session_id>/stream", methods=["GET"])
@login_required
def stream_ai_session(project_id: int, session_id: str):
    session = _get_authorized_session(project_id, session_id)

    def generate():
        yield "event: ready\ndata: session-ready\n\n"
        yield from stream_session(session)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@projects_bp.route("/<int:project_id>/ai/session/<session_id>/input", methods=["POST"])
@login_required
def send_ai_input(project_id: int, session_id: str):
    session = _get_authorized_session(project_id, session_id)
    payload = request.get_json(silent=True) or {}
    data = payload.get("data")
    if not data:
        return ("", 204)
    write_to_session(session, data)
    return ("", 204)


@projects_bp.route("/<int:project_id>/ai/session/<session_id>/resize", methods=["POST"])
@login_required
def resize_ai_session(project_id: int, session_id: str):
    session = _get_authorized_session(project_id, session_id)
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows")
    cols = payload.get("cols")
    if not isinstance(rows, int) or not isinstance(cols, int) or rows <= 0 or cols <= 0:
        return jsonify({"error": "rows and cols must be positive integers."}), 400
    resize_session(session, rows, cols)
    return ("", 204)


@projects_bp.route("/<int:project_id>/ai/session/<session_id>", methods=["DELETE"])
@login_required
def stop_ai_session(project_id: int, session_id: str):
    session = _get_authorized_session(project_id, session_id)
    close_session(session)
    return ("", 204)


@projects_bp.route("/<int:project_id>/ai/sessions/resumable", methods=["GET"])
@login_required
def list_resumable_sessions(project_id: int):
    """List resumable AI sessions for a project."""
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        return jsonify({"error": "Access denied"}), 403

    from ..services.ai_session_service import get_session_summary, get_user_sessions

    user_id = current_user.get_id()
    tool_filter = request.args.get("tool")  # Optional filter by tool

    sessions = get_user_sessions(
        user_id=int(user_id),
        project_id=project_id,
        tool=tool_filter,
        active_only=True,
    )

    session_data = [get_session_summary(s) for s in sessions]

    if request.is_json or request.accept_mimetypes.best == "application/json":
        return jsonify({"sessions": session_data})

    # Return HTML template for UI integration
    return render_template(
        "projects/resumable_sessions.html",
        project=project,
        sessions=session_data,
    )


@projects_bp.route(
    "/<int:project_id>/ai/sessions/<int:db_session_id>/resume", methods=["POST"]
)
@login_required
def resume_ai_session(project_id: int, db_session_id: int):
    """Resume an AI session by creating a new tmux session with the resume command."""
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        return jsonify({"error": "Access denied"}), 403

    from ..models import AISession as AISessionModel
    from ..services.ai_session_service import build_resume_command

    # Get the saved session from database
    db_session = AISessionModel.query.filter_by(
        id=db_session_id,
        project_id=project_id,
        user_id=int(current_user.get_id()),
    ).first_or_404()

    # Build the resume command
    resume_command = build_resume_command(db_session)

    # Parse JSON payload for terminal dimensions
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows")
    cols = payload.get("cols")

    # Create a new tmux session with the resume command
    try:
        session = create_session(
            project=project,
            user_id=int(current_user.get_id()),
            tool=db_session.tool,
            command=resume_command,
            rows=rows,
            cols=cols,
        )
        return jsonify({"session_id": session.id})
    except Exception as exc:
        current_app.logger.error("Failed to resume session: %s", exc)
        return jsonify({"error": str(exc)}), 500


@projects_bp.route("/<int:project_id>/tmux/close", methods=["POST"])
@login_required
def close_tmux_window(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        if request.is_json:
            return jsonify({"error": "Access denied"}), 403
        flash("You do not have access to this project.", "danger")
        return redirect(request.form.get("next") or url_for("admin.dashboard"))

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        tmux_target = (payload.get("tmux_target") or "").strip()
    else:
        tmux_target = (request.form.get("tmux_target") or "").strip()

    if not tmux_target:
        if request.is_json:
            return jsonify({"error": "Invalid tmux target."}), 400
        flash("Invalid tmux target.", "warning")
        redirect_target = request.form.get("next") or url_for("admin.dashboard")
        return redirect(redirect_target)

    linux_username = _current_linux_username()
    try:
        close_tmux_target(tmux_target, linux_username=linux_username)

        # Mark all sessions with this tmux target as inactive
        sessions = AISession.query.filter_by(
            tmux_target=tmux_target,
            is_active=True
        ).all()

        for session in sessions:
            session.is_active = False
            session.ended_at = datetime.now(timezone.utc)

        if sessions:
            db.session.commit()

    except TmuxServiceError as exc:
        if request.is_json:
            return jsonify({"error": str(exc)}), 500
        flash(str(exc), "danger")
    else:
        if not request.is_json:
            flash(f"Closed tmux window {tmux_target}.", "success")

    if request.is_json:
        return jsonify({"success": True})

    redirect_target = request.form.get("next") or url_for("admin.dashboard")
    return redirect(redirect_target)


@projects_bp.route("/<int:project_id>/tmux/respawn", methods=["POST"])
@login_required
def respawn_tmux_pane(project_id: int):
    """Respawn a dead tmux pane with its original command."""
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        if request.is_json:
            return jsonify({"error": "Access denied"}), 403
        flash("You do not have access to this project.", "danger")
        return redirect(request.form.get("next") or url_for("admin.dashboard"))

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        tmux_target = (payload.get("tmux_target") or "").strip()
    else:
        tmux_target = (request.form.get("tmux_target") or "").strip()

    if not tmux_target:
        if request.is_json:
            return jsonify({"error": "Invalid tmux target."}), 400
        flash("Invalid tmux target.", "warning")
        redirect_target = request.form.get("next") or url_for("admin.dashboard")
        return redirect(redirect_target)

    linux_username = _current_linux_username()
    try:
        from ..services.tmux_service import is_pane_dead, respawn_pane

        if not is_pane_dead(tmux_target, linux_username=linux_username):
            if request.is_json:
                return jsonify({"error": "Pane is not dead, cannot respawn."}), 400
            flash("Pane is still alive, no need to respawn.", "warning")
        else:
            respawn_pane(tmux_target, linux_username=linux_username)
            if not request.is_json:
                flash(f"Respawned tmux pane {tmux_target}.", "success")
    except TmuxServiceError as exc:
        if request.is_json:
            return jsonify({"error": str(exc)}), 500
        flash(str(exc), "danger")

    if request.is_json:
        return jsonify({"success": True})

    redirect_target = request.form.get("next") or url_for("admin.dashboard")
    return redirect(redirect_target)


@projects_bp.route("/<int:project_id>/ansible", methods=["GET", "POST"])
@login_required
def project_ansible_console(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    form = AnsibleForm()

    template_error = None
    template_choices: ChoiceList = []
    default_semaphore_project_id = current_app.config.get(
        "SEMAPHORE_DEFAULT_PROJECT_ID"
    )
    if (
        form.semaphore_project_id.data is None
        and default_semaphore_project_id is not None
    ):
        form.semaphore_project_id.data = default_semaphore_project_id

    selected_project_id = form.semaphore_project_id.data
    semaphore_configured = bool(
        current_app.config.get("SEMAPHORE_BASE_URL")
        and current_app.config.get("SEMAPHORE_API_TOKEN")
    )

    if not semaphore_configured:
        template_error = (
            "Semaphore integration is not configured. "
            "Define SEMAPHORE_BASE_URL and SEMAPHORE_API_TOKEN."
        )
    elif selected_project_id is None:
        template_error = "Provide a Semaphore Project ID to load templates."
    else:
        try:
            templates = get_semaphore_templates(int(selected_project_id))
            for template in templates:
                template_id = template.get("id")
                if template_id is None:
                    continue
                name = template.get("name") or f"Template {template_id}"
                playbook = template.get("playbook") or ""
                label = f"{name} (#{template_id})"
                if playbook:
                    label = f"{label} - {playbook}"
                template_choices.append((template_id, label))
        except (SemaphoreConfigError, SemaphoreAPIError) as exc:
            template_error = str(exc)

    form.template_id.choices = template_choices
    if form.template_id.data is None and template_choices:
        form.template_id.data = template_choices[0][0]

    message = None
    error = None
    task_result = None

    if form.validate_on_submit():
        try:
            result = run_ansible_playbook(
                project.name,
                form.semaphore_project_id.data,
                form.template_id.data,
                playbook=form.playbook.data or None,
                arguments=form.arguments.data or None,
                git_branch=form.git_branch.data or None,
                message=form.message.data or None,
                dry_run=bool(form.dry_run.data),
                debug=bool(form.debug.data),
                diff=bool(form.diff.data),
                limit=form.limit.data or None,
                inventory_id=form.inventory_id.data or None,
            )
            task_result = result
            if result["returncode"] == 0:
                message = result["stdout"]
            else:
                error = (
                    result["stderr"]
                    or f"Semaphore task ended with status {result.get('status') or 'unknown'}."
                )
        except (SemaphoreConfigError, SemaphoreAPIError, SemaphoreTimeoutError) as exc:
            error = str(exc)

    return render_template(
        "projects/ansible_console.html",
        project=project,
        form=form,
        message=message,
        error=error,
        task_result=task_result,
        template_error=template_error,
    )
