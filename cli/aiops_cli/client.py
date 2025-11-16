"""API client for AIops REST API."""

from typing import Any, Optional

import requests


class APIError(Exception):
    """API error exception."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        """Initialize API error.

        Args:
            message: Error message
            status_code: HTTP status code
        """
        super().__init__(message)
        self.status_code = status_code


class APIClient:
    """AIops REST API client."""

    def __init__(self, base_url: str, api_key: str):
        """Initialize API client.

        Args:
            base_url: API base URL (e.g., http://localhost:5000)
            api_key: API authentication key
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Make HTTP request to API.

        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            json: JSON request body

        Returns:
            Response data

        Raises:
            APIError: If request fails
        """
        url = f"{self.base_url}/api/v1/{path.lstrip('/')}"
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json,
            )
            response.raise_for_status()

            # Handle empty responses (204 No Content)
            if response.status_code == 204:
                return None

            return response.json()
        except requests.exceptions.HTTPError as exc:
            try:
                error_data = exc.response.json()
                error_msg = error_data.get("error", str(exc))
            except Exception:  # noqa: BLE001
                error_msg = str(exc)
            raise APIError(error_msg, exc.response.status_code) from exc
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Request failed: {exc}") from exc

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Make GET request."""
        return self._request("GET", path, params=params)

    def post(
        self, path: str, json: Optional[dict[str, Any]] = None, params: Optional[dict[str, Any]] = None
    ) -> Any:
        """Make POST request."""
        return self._request("POST", path, params=params, json=json)

    def patch(
        self, path: str, json: Optional[dict[str, Any]] = None
    ) -> Any:
        """Make PATCH request."""
        return self._request("PATCH", path, json=json)

    def delete(self, path: str) -> Any:
        """Make DELETE request."""
        return self._request("DELETE", path)

    # Authentication
    def whoami(self) -> dict[str, Any]:
        """Get current user info."""
        return self.get("auth/me")

    def list_api_keys(self) -> list[dict[str, Any]]:
        """List API keys."""
        data = self.get("auth/keys")
        return data.get("keys", [])

    def create_api_key(
        self, name: str, scopes: list[str], expires_days: Optional[int] = None
    ) -> dict[str, Any]:
        """Create API key."""
        payload = {"name": name, "scopes": scopes}
        if expires_days:
            payload["expires_days"] = expires_days
        return self.post("auth/keys", json=payload)

    def delete_api_key(self, key_id: int) -> None:
        """Delete API key."""
        self.delete(f"auth/keys/{key_id}")

    # Issues
    def list_issues(
        self,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        project_id: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """List issues."""
        params = {}
        if status:
            params["status"] = status
        if provider:
            params["provider"] = provider
        if project_id:
            params["project_id"] = project_id
        if limit:
            params["limit"] = limit
        data = self.get("issues", params=params)
        return data.get("issues", [])

    def get_issue(self, issue_id: int) -> dict[str, Any]:
        """Get issue details."""
        data = self.get(f"issues/{issue_id}")
        return data.get("issue", {})

    def create_issue(
        self,
        project_id: int,
        integration_id: int,
        title: str,
        description: Optional[str] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Create issue."""
        payload = {
            "project_id": project_id,
            "integration_id": integration_id,
            "title": title,
        }
        if description:
            payload["description"] = description
        if labels:
            payload["labels"] = labels
        return self.post("issues", json=payload)

    def update_issue(
        self,
        issue_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        labels: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Update issue."""
        payload = {}
        if title:
            payload["title"] = title
        if description:
            payload["description"] = description
        if labels is not None:
            payload["labels"] = labels
        return self.patch(f"issues/{issue_id}", json=payload)

    def close_issue(self, issue_id: int) -> dict[str, Any]:
        """Close issue."""
        return self.post(f"issues/{issue_id}/close")

    def add_issue_comment(self, issue_id: int, body: str) -> dict[str, Any]:
        """Add comment to issue."""
        return self.post(f"issues/{issue_id}/comments", json={"body": body})

    def assign_issue(self, issue_id: int, user_id: Optional[int] = None) -> dict[str, Any]:
        """Assign issue to user."""
        payload = {}
        if user_id:
            payload["user_id"] = user_id
        return self.post(f"issues/{issue_id}/assign", json=payload)

    def claim_issue(self, issue_id: int) -> dict[str, Any]:
        """Claim an issue (assign to self and get workspace info)."""
        return self.post("workflows/claim-issue", json={"issue_id": issue_id})

    def start_ai_session_on_issue(
        self,
        issue_id: int,
        tool: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """Start an AI session for working on an issue.

        This combines claim-issue workflow with starting an AI session.
        """
        # First claim the issue to get project info
        claim_result = self.claim_issue(issue_id)
        issue_data = claim_result.get("issue", {})
        workspace_data = claim_result.get("workspace", {})
        project_id = issue_data.get("project_id")

        if not project_id:
            raise APIError("Failed to get project_id from claim-issue response")

        # Start AI session (uses legacy /api endpoint, not /api/v1)
        payload = {"issue_id": issue_id}  # Track which issue this session is for
        if tool:
            payload["tool"] = tool
        if prompt:
            payload["prompt"] = prompt

        # AI sessions are not yet in v1 API, use legacy endpoint directly
        url = f"{self.base_url}/api/projects/{project_id}/ai/sessions"
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.HTTPError as exc:
            try:
                error_data = exc.response.json()
                error_msg = error_data.get("error", str(exc))
            except Exception:  # noqa: BLE001
                error_msg = str(exc)
            raise APIError(error_msg, exc.response.status_code) from exc
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Request failed: {exc}") from exc

        # Add project info to response
        result["project_id"] = project_id
        result["issue_id"] = issue_id
        result["workspace_path"] = workspace_data.get("path")
        # Pass through any warning from claim-issue
        if "warning" in claim_result:
            result["warning"] = claim_result["warning"]

        return result

    def list_ai_sessions(self, project_id: int) -> list[dict[str, Any]]:
        """List active AI sessions for a project.

        Args:
            project_id: Project ID to list sessions for

        Returns:
            List of active session dictionaries
        """
        url = f"{self.base_url}/api/projects/{project_id}/ai/sessions"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            result = response.json()
            return result.get("sessions", [])
        except requests.exceptions.HTTPError as exc:
            try:
                error_data = exc.response.json()
                error_msg = error_data.get("error", str(exc))
            except Exception:  # noqa: BLE001
                error_msg = str(exc)
            raise APIError(error_msg, exc.response.status_code) from exc
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Request failed: {exc}") from exc

    # Projects
    def list_projects(self, tenant_id: Optional[int] = None) -> list[dict[str, Any]]:
        """List projects."""
        params = {}
        if tenant_id:
            params["tenant_id"] = tenant_id
        data = self.get("projects", params=params)
        return data.get("projects", [])

    def get_project(self, project_id: int) -> dict[str, Any]:
        """Get project details."""
        data = self.get(f"projects/{project_id}")
        return data.get("project", {})

    def create_project(
        self,
        name: str,
        repo_url: str,
        tenant_id: int,
        description: Optional[str] = None,
        default_branch: str = "main",
    ) -> dict[str, Any]:
        """Create project."""
        payload = {
            "name": name,
            "repo_url": repo_url,
            "tenant_id": tenant_id,
            "default_branch": default_branch,
        }
        if description:
            payload["description"] = description
        return self.post("projects", json=payload)

    # Git operations
    def git_status(self, project_id: int) -> dict[str, Any]:
        """Get git status."""
        data = self.get(f"projects/{project_id}/git/status")
        return data.get("status", {})

    def git_pull(self, project_id: int, ref: Optional[str] = None) -> dict[str, Any]:
        """Pull git changes."""
        params = {}
        if ref:
            params["ref"] = ref
        return self.post(f"projects/{project_id}/git/pull", params=params)

    def git_push(self, project_id: int, ref: Optional[str] = None) -> dict[str, Any]:
        """Push git changes."""
        params = {}
        if ref:
            params["ref"] = ref
        return self.post(f"projects/{project_id}/git/push", params=params)

    def git_commit(
        self, project_id: int, message: str, files: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Create git commit."""
        payload = {"message": message}
        if files:
            payload["files"] = files
        return self.post(f"projects/{project_id}/git/commit", json=payload)

    def git_branches(self, project_id: int) -> list[dict[str, Any]]:
        """List git branches."""
        data = self.get(f"projects/{project_id}/git/branches")
        return data.get("branches", [])

    def git_create_branch(
        self, project_id: int, name: str, from_branch: Optional[str] = None
    ) -> dict[str, Any]:
        """Create git branch."""
        payload = {"name": name}
        if from_branch:
            payload["from_branch"] = from_branch
        return self.post(f"projects/{project_id}/git/branches", json=payload)

    def git_checkout(self, project_id: int, branch: str) -> dict[str, Any]:
        """Checkout git branch."""
        return self.post(f"projects/{project_id}/git/checkout", json={"branch": branch})

    def git_list_files(self, project_id: int, path: str = "") -> list[dict[str, Any]]:
        """List files in repository."""
        params = {"path": path} if path else {}
        data = self.get(f"projects/{project_id}/files", params=params)
        return data.get("files", [])

    def git_read_file(self, project_id: int, file_path: str) -> str:
        """Read file from repository."""
        data = self.get(f"projects/{project_id}/files/{file_path}")
        return data.get("content", "")

    # Workflows
    def workflow_claim_issue(self, issue_id: int) -> dict[str, Any]:
        """Claim issue for work."""
        return self.post("workflows/claim-issue", json={"issue_id": issue_id})

    def workflow_update_progress(
        self, issue_id: int, status: str, comment: Optional[str] = None
    ) -> dict[str, Any]:
        """Update issue progress."""
        payload = {"issue_id": issue_id, "status": status}
        if comment:
            payload["comment"] = comment
        return self.post("workflows/update-progress", json=payload)

    def workflow_submit_changes(
        self,
        issue_id: int,
        project_id: int,
        commit_message: str,
        files: Optional[list[str]] = None,
        comment: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit changes for issue."""
        payload = {
            "issue_id": issue_id,
            "project_id": project_id,
            "commit_message": commit_message,
        }
        if files:
            payload["files"] = files
        if comment:
            payload["comment"] = comment
        return self.post("workflows/submit-changes", json=payload)

    def workflow_request_approval(
        self, issue_id: int, message: Optional[str] = None
    ) -> dict[str, Any]:
        """Request approval for changes."""
        payload = {"issue_id": issue_id}
        if message:
            payload["message"] = message
        return self.post("workflows/request-approval", json=payload)

    def workflow_complete_issue(
        self, issue_id: int, summary: Optional[str] = None
    ) -> dict[str, Any]:
        """Complete issue."""
        payload = {"issue_id": issue_id}
        if summary:
            payload["summary"] = summary
        return self.post("workflows/complete-issue", json=payload)

    # Tenants
    def list_tenants(self) -> list[dict[str, Any]]:
        """List tenants."""
        data = self.get("tenants")
        return data.get("tenants", [])

    def get_tenant(self, tenant_id: int) -> dict[str, Any]:
        """Get tenant details."""
        data = self.get(f"tenants/{tenant_id}")
        return data.get("tenant", {})

    def create_tenant(
        self, name: str, description: Optional[str] = None, color: Optional[str] = None
    ) -> dict[str, Any]:
        """Create tenant."""
        payload = {"name": name}
        if description:
            payload["description"] = description
        if color:
            payload["color"] = color
        return self.post("tenants", json=payload)
