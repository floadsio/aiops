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
    # Dependency listing
    "list_inventories",
    "list_environments",
    "list_repositories",
    "list_keys",
    # Template CRUD
    "create_template",
    "update_template",
    "delete_template",
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
    limit: Optional[str] = None,
    tags: Optional[str] = None,
    skip_tags: Optional[str] = None,
) -> dict[str, Any]:
    """Run a Semaphore template.

    Args:
        project: aiops Project
        template_id: Semaphore template ID
        variables: Optional survey variables
        environment: Optional environment override
        limit: Optional Ansible host limit (comma-separated)
        tags: Optional Ansible tags to run (comma-separated)
        skip_tags: Optional Ansible tags to skip (comma-separated)

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

    # Runtime overrides - limit is top-level string, tags go in arguments
    if limit:
        payload["limit"] = limit

    # Tags/skip_tags must be passed as --tags/--skip-tags in arguments
    if tags or skip_tags:
        args = []
        if tags:
            args.append(f"--tags={tags}")
        if skip_tags:
            args.append(f"--skip-tags={skip_tags}")
        payload["arguments"] = " ".join(args)

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


# -----------------------------------------------------------------------------
# Dependency listing functions
# -----------------------------------------------------------------------------


def list_inventories(project: Project) -> list[dict[str, Any]]:
    """List inventories for a project's Semaphore project.

    Args:
        project: aiops Project with semaphore_project_id set

    Returns:
        List of inventories
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    response = client._request(
        "get",
        f"/project/{project.semaphore_project_id}/inventory",
    )
    data = client._read_json(response)
    if not isinstance(data, list):
        raise SemaphoreAPIError("Unexpected response format for inventories")
    return data


def list_environments(project: Project) -> list[dict[str, Any]]:
    """List environments for a project's Semaphore project.

    Args:
        project: aiops Project with semaphore_project_id set

    Returns:
        List of environments
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    response = client._request(
        "get",
        f"/project/{project.semaphore_project_id}/environment",
    )
    data = client._read_json(response)
    if not isinstance(data, list):
        raise SemaphoreAPIError("Unexpected response format for environments")
    return data


def list_repositories(project: Project) -> list[dict[str, Any]]:
    """List repositories for a project's Semaphore project.

    Args:
        project: aiops Project with semaphore_project_id set

    Returns:
        List of repositories
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    response = client._request(
        "get",
        f"/project/{project.semaphore_project_id}/repositories",
    )
    data = client._read_json(response)
    if not isinstance(data, list):
        raise SemaphoreAPIError("Unexpected response format for repositories")
    return data


def list_keys(project: Project) -> list[dict[str, Any]]:
    """List SSH keys for a project's Semaphore project.

    Args:
        project: aiops Project with semaphore_project_id set

    Returns:
        List of SSH keys
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)
    response = client._request(
        "get",
        f"/project/{project.semaphore_project_id}/keys",
    )
    data = client._read_json(response)
    if not isinstance(data, list):
        raise SemaphoreAPIError("Unexpected response format for keys")
    return data


# -----------------------------------------------------------------------------
# Template CRUD functions
# -----------------------------------------------------------------------------


def create_template(
    project: Project,
    name: str,
    playbook: str,
    inventory_id: int,
    repository_id: int,
    environment_id: int,
    app: str = "ansible",
    arguments: Optional[list[str]] = None,
    description: Optional[str] = None,
    limit: Optional[str] = None,
    tags: Optional[str] = None,
    skip_tags: Optional[str] = None,
    allow_override_args: Optional[bool] = None,
    suppress_success_alerts: Optional[bool] = None,
    autorun: Optional[bool] = None,
    view_id: Optional[int] = None,
    git_branch: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new Semaphore template.

    Args:
        project: aiops Project with semaphore_project_id set
        name: Template display name
        playbook: Path to playbook file (e.g., 'ansible/playbook.yml')
        inventory_id: Semaphore inventory ID
        repository_id: Semaphore repository ID
        environment_id: Semaphore environment ID
        app: Application type (ansible, terraform, tofu, bash, powershell)
        arguments: Optional list of extra CLI arguments
        description: Optional template description
        limit: Host limitation pattern (e.g., 'webservers' or 'host1,host2')
        tags: Ansible tags to run (e.g., 'deploy,config' or 'setup')
        skip_tags: Ansible tags to skip (e.g., 'slow,dangerous')
        allow_override_args: Allow overriding arguments per task run
        suppress_success_alerts: Disable success notifications
        autorun: Enable automatic execution trigger
        view_id: Dashboard/view ID for grouping
        git_branch: Repository branch to use

    Returns:
        Created template details
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)

    import json

    payload: dict[str, Any] = {
        "name": name,
        "playbook": playbook,
        "inventory_id": inventory_id,
        "repository_id": repository_id,
        "environment_id": environment_id,
        "app": app,
    }

    if arguments:
        payload["arguments"] = json.dumps(arguments)
    if description:
        payload["description"] = description
    if allow_override_args is not None:
        payload["allow_override_args_in_task"] = allow_override_args
    if suppress_success_alerts is not None:
        payload["suppress_success_alerts"] = suppress_success_alerts
    if autorun is not None:
        payload["autorun"] = autorun
    if view_id is not None:
        payload["view_id"] = view_id
    if git_branch:
        payload["git_branch"] = git_branch

    # Ansible-specific params go in task_params (limit/tags must be arrays)
    if app == "ansible" and (limit or tags or skip_tags):
        task_params: dict[str, Any] = {}

        if limit:
            # Convert comma-separated string to array
            if isinstance(limit, str):
                task_params["limit"] = [h.strip() for h in limit.split(",") if h.strip()]
            else:
                task_params["limit"] = list(limit)
            task_params["allow_override_limit"] = True

        if tags:
            # Convert comma-separated string to array
            if isinstance(tags, str):
                task_params["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            else:
                task_params["tags"] = list(tags)
            task_params["allow_override_tags"] = True

        if skip_tags:
            # Convert comma-separated string to array
            if isinstance(skip_tags, str):
                task_params["skip_tags"] = [t.strip() for t in skip_tags.split(",") if t.strip()]
            else:
                task_params["skip_tags"] = list(skip_tags)
            task_params["allow_override_skip_tags"] = True

        payload["task_params"] = task_params

    response = client._request(
        "post",
        f"/project/{project.semaphore_project_id}/templates",
        json_body=payload,
    )
    template = client._read_json(response)

    log.info(
        "Created Semaphore template '%s' (ID %s) for project %s",
        name,
        template.get("id"),
        project.name,
    )

    return template


def update_template(
    project: Project,
    template_id: int,
    name: Optional[str] = None,
    playbook: Optional[str] = None,
    inventory_id: Optional[int] = None,
    repository_id: Optional[int] = None,
    environment_id: Optional[int] = None,
    app: Optional[str] = None,
    arguments: Optional[list[str]] = None,
    description: Optional[str] = None,
    limit: Optional[str] = None,
    tags: Optional[str] = None,
    skip_tags: Optional[str] = None,
    allow_override_args: Optional[bool] = None,
    suppress_success_alerts: Optional[bool] = None,
    autorun: Optional[bool] = None,
    view_id: Optional[int] = None,
    git_branch: Optional[str] = None,
) -> dict[str, Any]:
    """Update an existing Semaphore template.

    Args:
        project: aiops Project with semaphore_project_id set
        template_id: Semaphore template ID to update
        name: New template display name
        playbook: New path to playbook file
        inventory_id: New Semaphore inventory ID
        repository_id: New Semaphore repository ID
        environment_id: New Semaphore environment ID
        app: New application type
        arguments: New list of extra CLI arguments
        description: New template description
        limit: Host limitation pattern
        tags: Ansible tags to run (e.g., 'deploy,config')
        skip_tags: Ansible tags to skip (e.g., 'slow,dangerous')
        allow_override_args: Allow overriding arguments per task run
        suppress_success_alerts: Disable success notifications
        autorun: Enable automatic execution trigger
        view_id: Dashboard/view ID for grouping
        git_branch: Repository branch to use

    Returns:
        Updated template details
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)

    # Get current template to merge changes
    current = get_template(project, template_id)

    import json

    payload: dict[str, Any] = {
        "id": template_id,
        "project_id": project.semaphore_project_id,
        "name": name if name is not None else current.get("name"),
        "playbook": playbook if playbook is not None else current.get("playbook"),
        "inventory_id": inventory_id if inventory_id is not None else current.get("inventory_id"),
        "repository_id": repository_id if repository_id is not None else current.get("repository_id"),
        "environment_id": environment_id if environment_id is not None else current.get("environment_id"),
        "app": app if app is not None else current.get("app", "ansible"),
    }

    if arguments is not None:
        payload["arguments"] = json.dumps(arguments)
    elif current.get("arguments"):
        payload["arguments"] = current["arguments"]

    if description is not None:
        payload["description"] = description
    elif current.get("description"):
        payload["description"] = current["description"]

    # Handle limit/tags in task_params for Ansible templates
    current_app = app if app is not None else current.get("app", "ansible")
    current_task_params = current.get("task_params", {}) or {}

    if current_app == "ansible" and (limit is not None or tags is not None or skip_tags is not None):
        new_task_params = {**current_task_params}

        if limit is not None:
            if isinstance(limit, str):
                new_task_params["limit"] = [h.strip() for h in limit.split(",") if h.strip()]
            else:
                new_task_params["limit"] = list(limit)
            new_task_params["allow_override_limit"] = True

        if tags is not None:
            if isinstance(tags, str):
                new_task_params["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            else:
                new_task_params["tags"] = list(tags)
            new_task_params["allow_override_tags"] = True

        if skip_tags is not None:
            if isinstance(skip_tags, str):
                new_task_params["skip_tags"] = [t.strip() for t in skip_tags.split(",") if t.strip()]
            else:
                new_task_params["skip_tags"] = list(skip_tags)
            new_task_params["allow_override_skip_tags"] = True

        payload["task_params"] = new_task_params
    elif current_task_params:
        payload["task_params"] = current_task_params

    if allow_override_args is not None:
        payload["allow_override_args_in_task"] = allow_override_args
    elif current.get("allow_override_args_in_task") is not None:
        payload["allow_override_args_in_task"] = current["allow_override_args_in_task"]

    if suppress_success_alerts is not None:
        payload["suppress_success_alerts"] = suppress_success_alerts
    elif current.get("suppress_success_alerts") is not None:
        payload["suppress_success_alerts"] = current["suppress_success_alerts"]

    if autorun is not None:
        payload["autorun"] = autorun
    elif current.get("autorun") is not None:
        payload["autorun"] = current["autorun"]

    if view_id is not None:
        payload["view_id"] = view_id
    elif current.get("view_id") is not None:
        payload["view_id"] = current["view_id"]

    if git_branch is not None:
        payload["git_branch"] = git_branch
    elif current.get("git_branch"):
        payload["git_branch"] = current["git_branch"]

    response = client._request(
        "put",
        f"/project/{project.semaphore_project_id}/templates/{template_id}",
        json_body=payload,
    )

    # PUT may return empty, fetch the updated template
    if response.status == 204 or not response.body:
        template = get_template(project, template_id)
    else:
        template = client._read_json(response)

    log.info(
        "Updated Semaphore template %s for project %s",
        template_id,
        project.name,
    )

    return template


def delete_template(project: Project, template_id: int) -> None:
    """Delete a Semaphore template.

    Args:
        project: aiops Project with semaphore_project_id set
        template_id: Semaphore template ID to delete
    """
    if not project.semaphore_project_id:
        raise SemaphoreConfigError(
            f"Project '{project.name}' has no Semaphore project linked"
        )

    client = get_semaphore_client(project.tenant_id)

    client._request(
        "delete",
        f"/project/{project.semaphore_project_id}/templates/{template_id}",
    )

    log.info(
        "Deleted Semaphore template %s for project %s",
        template_id,
        project.name,
    )
