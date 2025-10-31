from __future__ import annotations

import shlex
from collections import Counter
from datetime import datetime, timezone
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
    jsonify,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..forms.project import AIRunForm, AnsibleForm, GitActionForm, IssueCreateForm, ProjectKeyForm
from sqlalchemy.orm import selectinload

from ..models import ExternalIssue, Project, ProjectIntegration, SSHKey
from ..services.ansible_runner import (
    get_semaphore_templates,
    run_ansible_playbook,
    SemaphoreAPIError,
    SemaphoreConfigError,
    SemaphoreTimeoutError,
)
from ..services.git_service import get_repo_status, run_git_action
from ..services.tmux_service import (
    list_windows_for_aliases,
    TmuxServiceError,
    get_or_create_window_for_project,
)
from ..services.issues.context import build_issue_agent_file, build_issue_prompt
from ..services.issues import (
    CREATE_PROVIDER_REGISTRY,
    IssueSyncError,
    create_issue_for_project_integration,
    sync_project_integration,
)
from ..services.issues.utils import normalize_issue_status
from ..ai_sessions import (
    close_session,
    create_session,
    get_session,
    resize_session,
    stream_session,
    write_to_session,
)

projects_bp = Blueprint("projects", __name__, template_folder="../templates/projects")


def _authorize(project: Project) -> bool:
    if current_user.is_admin:
        return True
    return project.owner_id == current_user.model.id


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
            selectinload(Project.issue_integrations).selectinload(ProjectIntegration.integration),
            selectinload(Project.issue_integrations).selectinload(ProjectIntegration.issues),
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
    key_choices = [(0, "Use tenant default")]
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
                return redirect(url_for("projects.project_detail", project_id=project.id))
        project.ssh_key = selected_key
        db.session.commit()
        if selected_key is None:
            flash("Project will use the tenant default SSH key.", "success")
        else:
            flash(f"Project SSH key updated to {selected_key.name}.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))
    elif ssh_key_form.submit.data:
        flash("Unable to update project SSH key. Please review the selection.", "danger")
    elif git_form.submit.data and git_form.validate_on_submit():
        try:
            message = run_git_action(
                project,
                git_form.action.data,
                git_form.ref.data or None,
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
                description = (
                    (form.description.data or "").strip() or None
                )
                issue_type_value = (
                    (form.issue_type.data or "").strip() or None
                )
                labels_raw = form.labels.data or ""
                labels = [
                    label.strip()
                    for label in labels_raw.split(",")
                    if label.strip()
                ]

                try:
                    payload = create_issue_for_project_integration(
                        link,
                        summary=summary,
                        description=description,
                        issue_type=issue_type_value,
                        labels=labels or None,
                    )
                    sync_project_integration(link)
                    db.session.commit()
                except IssueSyncError as exc:
                    db.session.rollback()
                    flash(f"Failed to create issue: {exc}", "danger")
                except Exception as exc:  # noqa: BLE001
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
                        integration.name
                        or (integration.provider or "Integration").title()
                    ) if integration else "Integration"
                    flash(
                        f"Created issue {payload.external_id} via {provider_display}.",
                        "success",
                    )
                    return redirect(url_for("projects.project_detail", project_id=project.id))
            else:
                flash("Please correct the errors in the issue form.", "danger")
            break

    status = get_repo_status(project)

    codex_command = current_app.config["ALLOWED_AI_TOOLS"].get(
        "codex", current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    )

    def _format_timestamp(value):
        if value is None:
            return None
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone().strftime("%b %d, %Y • %H:%M %Z")

    issue_groups: list[dict[str, object]] = []
    total_issue_count = 0
    all_project_issues = [
        issue
        for link in project.issue_integrations
        for issue in link.issues
    ]
    sorted_project_issues = sorted(all_project_issues, key=_issue_sort_key, reverse=True)

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
            issue_payload = {
                "id": record.id,
                "external_id": record.external_id,
                "title": record.title,
                "status": record.status,
                "assignee": record.assignee,
                "url": record.url,
                "labels": record.labels or [],
                "updated_display": updated_display,
            }
            issue_entries.append(
                {
                    **issue_payload,
                    "codex_payload": {
                        "prompt": build_issue_prompt(project, record, sorted_project_issues),
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
                "integration_name": integration.name if integration else "Unknown Integration",
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

    return render_template(
        "projects/detail.html",
        project=project,
        git_form=git_form,
        status=status,
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
    )


@projects_bp.route("/<int:project_id>/ai", methods=["GET"])
@login_required
def project_ai_console(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    form = AIRunForm()
    choices = [
        ("", "Manual Shell"),
    ] + [
        (key, key.capitalize()) for key in current_app.config["ALLOWED_AI_TOOLS"]
    ]
    form.ai_tool.choices = choices

    tmux_windows: list = []
    tmux_error: str | None = None
    tenant = project.tenant
    tenant_name = tenant.name if tenant else ""
    try:
        # Ensure a window exists for this project so users can attach immediately
        project_window = get_or_create_window_for_project(project)
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
        "codex", current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    )

    return render_template(
        "projects/ai_console.html",
        project=project,
        form=form,
        tmux_windows=tmux_windows,
        tmux_error=tmux_error,
        requested_tmux_target=requested_target,
        default_codex_command=default_codex_command,
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

    all_issues = sorted(
        ExternalIssue.query.join(ProjectIntegration)
        .filter(ProjectIntegration.project_id == project_id)
        .all(),
        key=_issue_sort_key,
        reverse=True,
    )

    prompt = build_issue_prompt(project, issue, all_issues)
    agent_path = build_issue_agent_file(project, issue, all_issues)

    codex_command = current_app.config["ALLOWED_AI_TOOLS"].get(
        "codex", current_app.config.get("DEFAULT_AI_SHELL", "/bin/bash")
    )
    command = f"{codex_command} --agent {shlex.quote(str(agent_path))}"

    return jsonify({
        "prompt": prompt,
        "command": command,
        "tool": "codex",
        "agent_path": str(agent_path),
        "tmux_target": get_or_create_window_for_project(project).target,
    })


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

    rows = rows if isinstance(rows, int) and rows > 0 else None
    cols = cols if isinstance(cols, int) and cols > 0 else None

    try:
        session = create_session(
            project,
            current_user.model.id,
            tool=tool,
            command=command,
            rows=rows,
            cols=cols,
            tmux_target=tmux_target,
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


@projects_bp.route("/<int:project_id>/ansible", methods=["GET", "POST"])
@login_required
def project_ansible_console(project_id: int):
    project = Project.query.get_or_404(project_id)
    if not _authorize(project):
        flash("You do not have access to this project.", "danger")
        return redirect(url_for("admin.dashboard"))

    form = AnsibleForm()

    template_error = None
    template_choices: list[tuple[int, str]] = []
    default_semaphore_project_id = current_app.config.get("SEMAPHORE_DEFAULT_PROJECT_ID")
    if form.semaphore_project_id.data is None and default_semaphore_project_id is not None:
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
