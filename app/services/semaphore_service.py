"""High-level Semaphore integration service.

Wraps SemaphoreClient with aiops context (tenant, project).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..models import Project, TenantIntegration
from .semaphore_client import (
    SemaphoreAPIError,
    SemaphoreClient,
    SemaphoreConfigError,
    SemaphoreError,
    SemaphoreTimeoutError,
)

log = logging.getLogger(__name__)

__all__ = [
    "SemaphoreAPIError",
    "SemaphoreConfigError",
    "SemaphoreError",
    "SemaphoreTimeoutError",
    "get_semaphore_client",
    "get_semaphore_integration",
    "get_project_templates",
    "run_template",
    "get_task_status",
    "get_task_logs",
    "list_semaphore_projects",
    "test_connection",
]


def get_semaphore_integration(tenant_id: int) -> TenantIntegration:
    """Get the Semaphore integration for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        TenantIntegration for Semaphore

    Raises:
        SemaphoreConfigError: If no Semaphore integration is configured
    """
    integration = TenantIntegration.query.filter_by(
        tenant_id=tenant_id,
        provider="semaphore",
        enabled=True,
    ).first()

    if not integration:
        raise SemaphoreConfigError(
            f"No Semaphore integration configured for tenant {tenant_id}"
        )

    return integration


def get_semaphore_client(tenant_id: int) -> SemaphoreClient:
    """Get a SemaphoreClient for the tenant's integration.

    Args:
        tenant_id: Tenant ID

    Returns:
        Configured SemaphoreClient

    Raises:
        SemaphoreConfigError: If no Semaphore integration is configured
    """
    integration = get_semaphore_integration(tenant_id)

    if not integration.base_url:
        raise SemaphoreConfigError("Semaphore integration missing base URL")
    if not integration.api_token:
        raise SemaphoreConfigError("Semaphore integration missing API token")

    return SemaphoreClient(
        base_url=integration.base_url,
        token=integration.api_token,
    )


def test_connection(tenant_id: int) -> dict[str, Any]:
    """Test connection to Semaphore API.

    Args:
        tenant_id: Tenant ID

    Returns:
        Dict with connection status and project list
    """
    try:
        projects = list_semaphore_projects(tenant_id)
        return {
            "success": True,
            "message": f"Connected successfully. Found {len(projects)} projects.",
            "projects": projects,
        }
    except SemaphoreError as e:
        return {
            "success": False,
            "message": str(e),
            "projects": [],
        }


def list_semaphore_projects(tenant_id: int) -> list[dict[str, Any]]:
    """List all projects in Semaphore.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of Semaphore projects
    """
    client = get_semaphore_client(tenant_id)
    response = client._request("get", "/projects")
    data = client._read_json(response)
    if not isinstance(data, list):
        raise SemaphoreAPIError("Unexpected response format for projects")
    return data


def get_project_templates(project: Project) -> list[dict[str, Any]]:
    """Get templates for a project's linked Semaphore project.

    Args:
        project: aiops Project with semaphore_project_id set

    Returns:
        List of templates

    Raises:
        SemaphoreConfigError: If project has no Semaphore project linked
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    return client.list_templates(project.semaphore_project_id)


def get_template(project: Project, template_id: int) -> dict[str, Any]:
    """Get a specific template by ID.

    Args:
        project: aiops Project
        template_id: Semaphore template ID

    Returns:
        Template details
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    response = client._request(
        "get",
        f"/project/{project.semaphore_project_id}/templates/{template_id}",
    )
    return client._read_json(response)


def run_template(
    project: Project,
    template_id: int,
    variables: Optional[dict[str, Any]] = None,
    environment: Optional[str] = None,
) -> dict[str, Any]:
    """Run a Semaphore template.

    Args:
        project: aiops Project
        template_id: Semaphore template ID
        variables: Optional survey variables
        environment: Optional environment override

    Returns:
        Task details including task ID
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)

    payload: dict[str, Any] = {}
    if variables:
        payload["environment"] = variables
    if environment:
        payload["environment"] = environment

    task = client.start_task(
        project_id=project.semaphore_project_id,
        template_id=template_id,
        payload=payload if payload else None,
    )

    log.info(
        "Started Semaphore task %s for project %s (template %s)",
        task.get("id"),
        project.name,
        template_id,
    )

    return task


def get_task_status(project: Project, task_id: int) -> dict[str, Any]:
    """Get status of a Semaphore task.

    Args:
        project: aiops Project
        task_id: Semaphore task ID

    Returns:
        Task details including status
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    return client.get_task(project.semaphore_project_id, task_id)


def get_task_logs(project: Project, task_id: int) -> str:
    """Get logs/output of a Semaphore task.

    Args:
        project: aiops Project
        task_id: Semaphore task ID

    Returns:
        Task output as string
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    return client.get_task_output(project.semaphore_project_id, task_id)


def wait_for_task(
    project: Project,
    task_id: int,
    poll_interval: float = 2.0,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Wait for a Semaphore task to complete.

    Args:
        project: aiops Project
        task_id: Semaphore task ID
        poll_interval: Seconds between status checks
        timeout: Maximum seconds to wait

    Returns:
        Final task details

    Raises:
        SemaphoreTimeoutError: If task doesn't complete within timeout
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    return client.wait_for_task(
        project.semaphore_project_id,
        task_id,
        poll_interval=poll_interval,
        timeout=timeout,
    )


def list_tasks(
    project: Project,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List recent tasks for a project's Semaphore project.

    Args:
        project: aiops Project
        limit: Maximum number of tasks to return

    Returns:
        List of recent tasks
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    response = client._request(
        "get",
        f"/project/{project.semaphore_project_id}/tasks",
        params={"count": limit},
    )
    data = client._read_json(response)
    if not isinstance(data, list):
        raise SemaphoreAPIError("Unexpected response format for tasks")
    return data
