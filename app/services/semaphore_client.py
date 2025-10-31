from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib import error as urlerror
from urllib import parse, request as urlrequest

TERMINAL_STATUSES = {
    "error",
    "failed",
    "success",
    "stopped",
    "warning",
    "timeout",
    "cancelled",
    "canceled",
    "completed",
    "unknown",
    "aborted",
}


class SemaphoreError(Exception):
    """Base exception for Semaphore integration errors."""


class SemaphoreConfigError(SemaphoreError):
    """Raised when Semaphore integration is not configured."""


class SemaphoreAPIError(SemaphoreError):
    """Raised when the Semaphore API returns an error response."""


class SemaphoreTimeoutError(SemaphoreError):
    """Raised when waiting for a Semaphore task exceeds the allotted timeout."""


@dataclass
class _SimpleResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _build_error_message(status: int, body: bytes, method: str, path: str) -> str:
    detail: Optional[str] = None
    text = body.decode("utf-8", errors="replace").strip()
    if text:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                detail = (
                    str(data.get("error"))
                    or str(data.get("message"))
                    or str(data.get("detail"))
                )
            elif data:
                detail = str(data)
        except json.JSONDecodeError:
            detail = text
    detail = detail or "No additional error detail provided."
    return f"{method.upper()} {path} returned {status}: {detail}"


class SemaphoreClient:
    """Lightweight client for interacting with the Semaphore REST API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 15.0,
        verify: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("Semaphore base URL must be provided.")
        if not token:
            raise ValueError("Semaphore API token must be provided.")

        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api"
        self.timeout = timeout
        self.verify = verify
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def close(self) -> None:  # pragma: no cover - included for API parity
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: Iterable[int] = (200, 201, 204),
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> _SimpleResponse:
        method = method.upper()
        query = ""
        if params:
            query = "?" + parse.urlencode(params, doseq=True)
        url = f"{self.api_base}{path}{query}"

        request_headers = dict(self._headers)
        if headers:
            request_headers.update(headers)

        data_bytes: Optional[bytes] = None
        if json_body is not None:
            data_bytes = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        req = urlrequest.Request(url, data=data_bytes, method=method)
        for key, value in request_headers.items():
            req.add_header(key, value)

        context = None
        if not self.verify:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        try:
            with urlrequest.urlopen(req, timeout=self.timeout, context=context) as resp:
                body = resp.read()
                status = resp.status
                response_headers = dict(resp.getheaders())
        except urlerror.HTTPError as exc:
            body = exc.read()
            status = exc.code
            response_headers = dict(exc.headers.items()) if exc.headers else {}
        except urlerror.URLError as exc:  # pragma: no cover - network failure path
            raise SemaphoreAPIError(f"Error communicating with Semaphore API: {exc.reason}") from exc

        response = _SimpleResponse(status, response_headers, body)
        if status not in expected_status:
            raise SemaphoreAPIError(_build_error_message(status, body, method, path))
        return response

    def _read_json(self, response: _SimpleResponse) -> Any:
        try:
            return json.loads(response.text or "null")
        except json.JSONDecodeError as exc:
            raise SemaphoreAPIError("Semaphore API returned invalid JSON.") from exc

    def list_templates(self, project_id: int) -> list[dict[str, Any]]:
        response = self._request(
            "get",
            f"/project/{project_id}/templates",
            params={"sort": "name", "order": "asc"},
        )
        data = self._read_json(response)
        if not isinstance(data, list):
            raise SemaphoreAPIError("Semaphore API returned unexpected template data.")
        return data

    def start_task(
        self,
        project_id: int,
        template_id: int,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        body = {"template_id": template_id}
        if payload:
            body.update(payload)
        response = self._request(
            "post",
            f"/project/{project_id}/tasks",
            json_body=body,
            expected_status=(201,),
        )
        data = self._read_json(response)
        if not isinstance(data, dict):
            raise SemaphoreAPIError("Semaphore API returned unexpected task data.")
        return data

    def get_task(self, project_id: int, task_id: int) -> dict[str, Any]:
        response = self._request("get", f"/project/{project_id}/tasks/{task_id}")
        data = self._read_json(response)
        if not isinstance(data, dict):
            raise SemaphoreAPIError("Semaphore API returned unexpected task data.")
        return data

    def wait_for_task(
        self,
        project_id: int,
        task_id: int,
        *,
        poll_interval: float = 2.0,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        start_time = time.monotonic()

        while True:
            task = self.get_task(project_id, task_id)
            status = (task.get("status") or "").lower()
            if status in TERMINAL_STATUSES:
                return task

            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                raise SemaphoreTimeoutError(
                    f"Semaphore task {task_id} did not finish within {timeout} seconds."
                )
            time.sleep(poll_interval)

    def get_task_output(self, project_id: int, task_id: int) -> str:
        response = self._request(
            "get",
            f"/project/{project_id}/tasks/{task_id}/raw_output",
            expected_status=(200,),
            headers={"Accept": "text/plain"},
        )
        return response.text


__all__ = [
    "SemaphoreAPIError",
    "SemaphoreClient",
    "SemaphoreConfigError",
    "SemaphoreError",
    "SemaphoreTimeoutError",
]
