from __future__ import annotations

from typing import Any, Optional

from flask import current_app

from .semaphore_client import (
    SemaphoreAPIError,
    SemaphoreClient,
    SemaphoreConfigError,
    SemaphoreTimeoutError,
)

SUCCESS_STATUSES = {"success"}


def _get_semaphore_client() -> SemaphoreClient:
    base_url = current_app.config.get("SEMAPHORE_BASE_URL")
    token = current_app.config.get("SEMAPHORE_API_TOKEN")
    if not base_url or not token:
        raise SemaphoreConfigError(
            "Semaphore integration is not configured. Define SEMAPHORE_BASE_URL and SEMAPHORE_API_TOKEN."
        )

    verify_tls = current_app.config.get("SEMAPHORE_VERIFY_TLS", True)
    http_timeout = float(current_app.config.get("SEMAPHORE_HTTP_TIMEOUT", 15.0))

    return SemaphoreClient(
        base_url,
        token,
        timeout=http_timeout,
        verify=verify_tls,
    )


def get_semaphore_templates(project_id: int) -> list[dict[str, Any]]:
    client = _get_semaphore_client()
    return client.list_templates(project_id)


def run_ansible_playbook(
    project_name: str,
    semaphore_project_id: int,
    template_id: int,
    *,
    playbook: Optional[str] = None,
    arguments: Optional[str] = None,
    git_branch: Optional[str] = None,
    message: Optional[str] = None,
    dry_run: bool = False,
    debug: bool = False,
    diff: bool = False,
    limit: Optional[str] = None,
    inventory_id: Optional[int] = None,
) -> dict[str, Any]:
    client = _get_semaphore_client()

    payload: dict[str, Any] = {}
    if playbook:
        payload["playbook"] = playbook
    if arguments:
        payload["arguments"] = arguments
    if git_branch:
        payload["git_branch"] = git_branch
    if message:
        payload["message"] = message
    if limit:
        payload["limit"] = limit
    if inventory_id:
        payload["inventory_id"] = inventory_id

    if dry_run:
        payload["dry_run"] = True
    if debug:
        payload["debug"] = True
    if diff:
        payload["diff"] = True

    task = client.start_task(semaphore_project_id, template_id, payload)
    task_id = task.get("id")
    if task_id is None:
        raise SemaphoreAPIError("Semaphore response did not include a task id.")

    poll_interval = float(current_app.config.get("SEMAPHORE_POLL_INTERVAL", 2.0))
    task_timeout = float(current_app.config.get("SEMAPHORE_TASK_TIMEOUT", 600.0))

    final_task = client.wait_for_task(
        semaphore_project_id,
        task_id,
        poll_interval=poll_interval,
        timeout=task_timeout,
    )

    output = client.get_task_output(semaphore_project_id, task_id)
    status = (final_task.get("status") or "").lower()
    returncode = 0 if status in SUCCESS_STATUSES else 1

    return {
        "returncode": returncode,
        "stdout": output if returncode == 0 else "",
        "stderr": "" if returncode == 0 else output,
        "playbook": final_task.get("playbook") or playbook or "",
        "project": project_name,
        "status": final_task.get("status"),
        "task_id": task_id,
        "template_id": template_id,
        "semaphore_project_id": semaphore_project_id,
    }


__all__ = [
    "get_semaphore_templates",
    "run_ansible_playbook",
    "SemaphoreAPIError",
    "SemaphoreConfigError",
    "SemaphoreTimeoutError",
]
