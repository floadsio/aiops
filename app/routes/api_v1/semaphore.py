"""Semaphore API endpoints.

Provides REST API for Semaphore integration operations.
"""

from __future__ import annotations

from flask import g, jsonify, request

from ...extensions import db
from ...models import Project
from ...services.api_auth import require_api_auth
from ...services.semaphore_service import (
    SemaphoreConfigError,
    SemaphoreError,
    get_project_templates,
    get_task_logs,
    get_task_status,
    get_template,
    list_semaphore_projects,
    list_tasks,
    run_template,
    test_connection,
    wait_for_task,
)
from . import api_v1_bp


def _get_project_or_404(project_id: int) -> Project | None:
    """Get project by ID or return None."""
    return db.session.get(Project, project_id)


@api_v1_bp.route("/semaphore/projects", methods=["GET"])
@require_api_auth(scopes=["read"])
def semaphore_list_projects():
    """List Semaphore projects for the current user's tenant.

    Returns:
        JSON list of Semaphore projects
    """
    user = g.api_user

    # Get tenant from query param or user's projects
    tenant_id = request.args.get("tenant_id", type=int)
    if not tenant_id:
        project = Project.query.filter_by(owner_id=user.id).first()
        if project:
            tenant_id = project.tenant_id
        else:
            return jsonify({"error": "No tenant context available"}), 400

    try:
        projects = list_semaphore_projects(tenant_id)
        return jsonify(projects)
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500


@api_v1_bp.route("/semaphore/test", methods=["POST"])
@require_api_auth(scopes=["read"])
def semaphore_test_connection():
    """Test Semaphore connection for a tenant.

    Request body:
        tenant_id: int - Tenant ID to test

    Returns:
        JSON with connection status
    """
    data = request.get_json() or {}
    tenant_id = data.get("tenant_id")

    if not tenant_id:
        return jsonify({"error": "tenant_id is required"}), 400

    result = test_connection(tenant_id)
    status_code = 200 if result["success"] else 500
    return jsonify(result), status_code


@api_v1_bp.route("/projects/<int:project_id>/semaphore/templates", methods=["GET"])
@require_api_auth(scopes=["read"])
def project_semaphore_templates(project_id: int):
    """List Semaphore templates for a project.

    Args:
        project_id: aiops Project ID

    Returns:
        JSON list of templates
    """
    project = _get_project_or_404(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    try:
        templates = get_project_templates(project)
        return jsonify(templates)
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500


@api_v1_bp.route(
    "/projects/<int:project_id>/semaphore/templates/<int:template_id>",
    methods=["GET"],
)
@require_api_auth(scopes=["read"])
def project_semaphore_template_detail(project_id: int, template_id: int):
    """Get details of a specific Semaphore template.

    Args:
        project_id: aiops Project ID
        template_id: Semaphore template ID

    Returns:
        JSON template details
    """
    project = _get_project_or_404(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    try:
        template = get_template(project, template_id)
        return jsonify(template)
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500


@api_v1_bp.route("/projects/<int:project_id>/semaphore/run", methods=["POST"])
@require_api_auth(scopes=["write"])
def project_semaphore_run(project_id: int):
    """Run a Semaphore template.

    Args:
        project_id: aiops Project ID

    Request body:
        template_id: int - Semaphore template ID
        variables: dict - Optional survey variables

    Returns:
        JSON task details
    """
    project = _get_project_or_404(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json() or {}
    template_id = data.get("template_id")

    if not template_id:
        return jsonify({"error": "template_id is required"}), 400

    variables = data.get("variables")

    try:
        task = run_template(project, template_id, variables=variables)
        return jsonify(task), 201
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500


@api_v1_bp.route("/projects/<int:project_id>/semaphore/tasks", methods=["GET"])
@require_api_auth(scopes=["read"])
def project_semaphore_tasks(project_id: int):
    """List recent Semaphore tasks for a project.

    Args:
        project_id: aiops Project ID

    Query params:
        limit: int - Maximum tasks to return (default 20)

    Returns:
        JSON list of tasks
    """
    project = _get_project_or_404(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    limit = request.args.get("limit", 20, type=int)

    try:
        tasks = list_tasks(project, limit=limit)
        return jsonify(tasks)
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500


@api_v1_bp.route(
    "/projects/<int:project_id>/semaphore/tasks/<int:task_id>",
    methods=["GET"],
)
@require_api_auth(scopes=["read"])
def project_semaphore_task_status(project_id: int, task_id: int):
    """Get status of a Semaphore task.

    Args:
        project_id: aiops Project ID
        task_id: Semaphore task ID

    Returns:
        JSON task details
    """
    project = _get_project_or_404(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    try:
        task = get_task_status(project, task_id)
        return jsonify(task)
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500


@api_v1_bp.route(
    "/projects/<int:project_id>/semaphore/tasks/<int:task_id>/logs",
    methods=["GET"],
)
@require_api_auth(scopes=["read"])
def project_semaphore_task_logs(project_id: int, task_id: int):
    """Get logs/output of a Semaphore task.

    Args:
        project_id: aiops Project ID
        task_id: Semaphore task ID

    Returns:
        JSON with logs as text
    """
    project = _get_project_or_404(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    try:
        logs = get_task_logs(project, task_id)
        return jsonify({"logs": logs})
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500


@api_v1_bp.route(
    "/projects/<int:project_id>/semaphore/tasks/<int:task_id>/wait",
    methods=["POST"],
)
@require_api_auth(scopes=["read"])
def project_semaphore_task_wait(project_id: int, task_id: int):
    """Wait for a Semaphore task to complete.

    Args:
        project_id: aiops Project ID
        task_id: Semaphore task ID

    Request body:
        timeout: int - Maximum seconds to wait (default 600)
        poll_interval: float - Seconds between checks (default 2)

    Returns:
        JSON final task details
    """
    project = _get_project_or_404(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json() or {}
    timeout = data.get("timeout", 600)
    poll_interval = data.get("poll_interval", 2.0)

    try:
        task = wait_for_task(
            project,
            task_id,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        return jsonify(task)
    except SemaphoreConfigError as e:
        return jsonify({"error": str(e)}), 404
    except SemaphoreError as e:
        return jsonify({"error": str(e)}), 500
