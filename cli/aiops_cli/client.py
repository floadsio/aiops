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

    def put(
        self, path: str, json: Optional[dict[str, Any]] = None
    ) -> Any:
        """Make PUT request."""
        return self._request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        """Make DELETE request."""
        return self._request("DELETE", path)

    def _upload_request(
        self,
        method: str,
        path: str,
        files: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Make HTTP request with file uploads (multipart/form-data).

        Args:
            method: HTTP method
            path: API path
            files: Files to upload
            data: Form data

        Returns:
            Response data

        Raises:
            APIError: If request fails
        """
        url = f"{self.base_url}/api/v1/{path.lstrip('/')}"

        # Create headers without Content-Type (requests will set it for multipart)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            response = requests.request(
                method=method,
                url=url,
                files=files,
                data=data,
                headers=headers,
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

    # Authentication
    def whoami(self) -> dict[str, Any]:
        """Get current user info."""
        return self.get("auth/me")

    def is_admin(self) -> bool:
        """Check if current user is admin."""
        try:
            response = self.whoami()
            # The response is wrapped in {"user": {...}}
            user_info = response.get("user", {})
            return user_info.get("is_admin", False)
        except Exception:
            # If whoami fails, assume not admin for safety
            return False

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
    def list_pinned_issues(self) -> list[dict[str, Any]]:
        """List pinned issues for the current user.

        Returns:
            List of pinned issue dictionaries
        """
        url = f"{self.base_url}/api/v1/issues/pinned"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            result = response.json()
            return result.get("issues", [])
        except requests.exceptions.HTTPError as exc:
            try:
                error_data = exc.response.json()
                error_msg = error_data.get("error", str(exc))
            except Exception:  # noqa: BLE001
                error_msg = str(exc)
            raise APIError(error_msg, exc.response.status_code) from exc
        except requests.exceptions.RequestException as exc:
            raise APIError(f"Request failed: {exc}") from exc

    def pin_issue(self, issue_id: int) -> dict[str, Any]:
        """Pin an issue for quick access.

        Args:
            issue_id: Issue ID to pin

        Returns:
            Response data from the API
        """
        return self.post(f"issues/{issue_id}/pin")

    def unpin_issue(self, issue_id: int) -> dict[str, Any]:
        """Unpin an issue.

        Args:
            issue_id: Issue ID to unpin

        Returns:
            Response data from the API
        """
        return self.delete(f"issues/{issue_id}/pin")

    def list_issues(
        self,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        project_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
        assignee: Optional[str] = None,
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
        if tenant_id:
            params["tenant_id"] = tenant_id
        if assignee:
            params["assignee"] = assignee
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

    def remap_issue(self, issue_id: int, target_project_id: int) -> dict[str, Any]:
        """Remap an issue to a different aiops project.

        Args:
            issue_id: Issue database ID to remap
            target_project_id: Target project ID to remap to

        Returns:
            Response data with updated issue

        Note:
            This updates the internal aiops mapping only - the external issue tracker
            (GitHub/GitLab/Jira) remains unchanged. Requires admin access.
        """
        return self.post(f"issues/{issue_id}/remap", json={"project_id": target_project_id})

    def add_issue_comment(self, issue_id: int, body: str) -> dict[str, Any]:
        """Add comment to issue."""
        return self.post(f"issues/{issue_id}/comments", json={"body": body})

    def update_issue_comment(self, issue_id: int, comment_id: str, body: str) -> dict[str, Any]:
        """Update an existing comment on an issue."""
        return self.patch(f"issues/{issue_id}/comments/{comment_id}", json={"body": body})

    def assign_issue(self, issue_id: int, user_id: Optional[int] = None) -> dict[str, Any]:
        """Assign issue to user."""
        payload = {}
        if user_id:
            payload["user_id"] = user_id
        return self.post(f"issues/{issue_id}/assign", json=payload)

    def sync_issues(
        self,
        tenant_id: Optional[int] = None,
        integration_id: Optional[int] = None,
        project_id: Optional[int] = None,
        force_full: bool = False,
    ) -> dict[str, Any]:
        """Synchronize issues from external providers.

        Args:
            tenant_id: Limit sync to a specific tenant
            integration_id: Limit sync to a specific tenant integration
            project_id: Limit sync to a specific project
            force_full: Force full sync (default: False)

        Returns:
            Sync result with statistics
        """
        payload = {"force_full": force_full}
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        if integration_id is not None:
            payload["integration_id"] = integration_id
        if project_id is not None:
            payload["project_id"] = project_id
        return self.post("issues/sync", json=payload)

    def claim_issue(self, issue_id: int) -> dict[str, Any]:
        """Claim an issue (assign to self and get workspace info)."""
        return self.post("workflows/claim-issue", json={"issue_id": issue_id})

    def start_ai_session_on_issue(
        self,
        issue_id: int,
        tool: Optional[str] = None,
        prompt: Optional[str] = None,
        yolo: bool = False,
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

        # Start AI session
        payload = {"issue_id": issue_id}  # Track which issue this session is for
        if tool:
            payload["tool"] = tool
        if prompt:
            payload["prompt"] = prompt
        if yolo:
            payload["permission_mode"] = "yolo"

        import sys
        print(f"DEBUG [CLI]: Starting AI session for issue {issue_id}, tool={tool}, payload={payload}", file=sys.stderr)

        url = f"{self.base_url}/api/v1/projects/{project_id}/ai/sessions"
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

    def list_ai_sessions(self, project_id: int, all_users: bool = False) -> list[dict[str, Any]]:
        """List active AI sessions for a project.

        Args:
            project_id: Project ID to list sessions for
            all_users: If True, list sessions for all users (admin only)

        Returns:
            List of active session dictionaries
        """
        url = f"{self.base_url}/api/v1/projects/{project_id}/ai/sessions"
        params = {}
        if all_users:
            params["all_users"] = "true"

        try:
            response = self.session.get(url, params=params)
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

    def list_all_sessions(
        self,
        project_id: Optional[int] = None,
        all_users: bool = False,
        tool: Optional[str] = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List AI sessions across all projects.

        Args:
            project_id: Optional project ID filter
            all_users: If True, list sessions for all users (admin only)
            tool: Optional tool name filter
            active_only: Only return active sessions
            limit: Maximum number of sessions to return

        Returns:
            List of session dictionaries
        """
        params: dict[str, Any] = {
            "active_only": "true" if active_only else "false",
            "limit": limit,
        }
        if project_id is not None:
            params["project_id"] = project_id
        if all_users:
            params["all_users"] = "true"
        if tool:
            params["tool"] = tool

        data = self.get("ai/sessions", params=params)
        return data.get("sessions", [])

    def validate_session(self, session_db_id: int) -> dict[str, Any]:
        """Validate if a session's tmux target exists and mark inactive if not.

        Args:
            session_db_id: Database ID of the session to validate

        Returns:
            Validation result with 'exists' and 'marked_inactive' fields
        """
        return self.get(f"ai/sessions/{session_db_id}/validate")

    def upload_session_file(
        self, project_id: int, session_id: str, file_path: str, custom_name: Optional[str] = None
    ) -> dict[str, Any]:
        """Upload file to session workspace.

        Args:
            project_id: Project ID
            session_id: Session ID
            file_path: Path to file on local machine
            custom_name: Optional custom filename (defaults to original filename)

        Returns:
            Upload result with workspace_path, filename, and size
        """
        import os

        filename = custom_name or os.path.basename(file_path)

        with open(file_path, "rb") as f:
            files = {"file": (filename, f)}
            return self._upload_request(
                "POST", f"projects/{project_id}/ai/sessions/{session_id}/upload", files=files
            )

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

    def git_create_pr(
        self,
        project_id: int,
        title: str,
        description: str,
        source_branch: str,
        target_branch: str,
        assignee: Optional[str] = None,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a pull request (GitHub) or merge request (GitLab)."""
        payload = {
            "title": title,
            "description": description,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "draft": draft,
        }
        if assignee:
            payload["assignee"] = assignee
        return self.post(f"projects/{project_id}/pull-requests", json=payload)

    def git_merge_pr(
        self,
        project_id: int,
        pr_number: int,
        method: str = "merge",
        delete_branch: bool = False,
        commit_message: Optional[str] = None,
    ) -> dict[str, Any]:
        """Merge a pull request (GitHub) or merge request (GitLab)."""
        payload = {
            "method": method,
            "delete_branch": delete_branch,
        }
        if commit_message:
            payload["commit_message"] = commit_message
        return self.post(f"projects/{project_id}/pull-requests/{pr_number}/merge", json=payload)

    def close_pull_request(
        self,
        project_id: int,
        pr_number: int,
    ) -> dict[str, Any]:
        """Close a pull request (GitHub) or merge request (GitLab)."""
        return self.post(f"projects/{project_id}/pull-requests/{pr_number}/close")

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

    # Integrations
    def list_integrations(
        self, tenant_id: Optional[int] = None, provider: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List all integrations.

        Args:
            tenant_id: Optional tenant ID to filter by
            provider: Optional provider to filter by (github, gitlab, jira)

        Returns:
            List of integration dictionaries
        """
        params = {}
        if tenant_id:
            params["tenant_id"] = tenant_id
        if provider:
            params["provider"] = provider
        data = self.get("integrations", params=params)
        return data.get("integrations", [])

    def list_tenant_integrations(self, tenant_id: int) -> list[dict[str, Any]]:
        """List integrations for a specific tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of integration dictionaries
        """
        data = self.get(f"tenants/{tenant_id}/integrations")
        return data.get("integrations", [])

    # System management
    def system_update(self, skip_migrations: bool = False) -> dict[str, Any]:
        """Update the aiops application (git pull, install deps, run migrations).

        Args:
            skip_migrations: Skip database migrations

        Returns:
            Update result with detailed output
        """
        payload = {"skip_migrations": skip_migrations}
        return self.post("system/update", json=payload)

    def system_restart(self) -> dict[str, Any]:
        """Restart the aiops application.

        Returns:
            Restart confirmation
        """
        return self.post("system/restart")

    def system_update_and_restart(self, skip_migrations: bool = False) -> dict[str, Any]:
        """Update and restart the aiops application.

        Args:
            skip_migrations: Skip database migrations

        Returns:
            Update result and restart confirmation
        """
        payload = {"skip_migrations": skip_migrations}
        return self.post("system/update-and-restart", json=payload)

    def update_ai_tool(self, tool: str, source: str) -> dict[str, Any]:
        """Update one of the supported AI tool CLIs on the server.

        Args:
            tool: AI tool identifier (codex, gemini, claude)
            source: Update source (npm or brew)

        Returns:
            Command execution result payload
        """
        normalized_tool = tool.strip().lower()
        normalized_source = source.strip().lower()
        payload = {"source": normalized_source}
        return self.post(f"system/ai-tools/{normalized_tool}/update", json=payload)

    # System status
    def get_system_status(self) -> dict[str, Any]:
        """Get comprehensive system status for all components.

        Returns:
            System status with component health checks
        """
        return self.get("system/status")

    # Backup management
    def create_backup(self, description: str | None = None) -> dict[str, Any]:
        """Create a new database backup.

        Args:
            description: Optional description of the backup

        Returns:
            Backup creation result with metadata
        """
        payload = {}
        if description:
            payload["description"] = description
        return self.post("system/backups", json=payload)

    def list_backups(self) -> list[dict[str, Any]]:
        """List all available backups.

        Returns:
            List of backup metadata dictionaries
        """
        result = self.get("system/backups")
        return result.get("backups", [])

    def get_backup(self, backup_id: int) -> dict[str, Any]:
        """Get details of a specific backup.

        Args:
            backup_id: Database ID of the backup

        Returns:
            Backup metadata dictionary
        """
        result = self.get(f"system/backups/{backup_id}")
        return result.get("backup", {})

    def download_backup(self, backup_id: int, output_path: str) -> None:
        """Download a backup file.

        Args:
            backup_id: Database ID of the backup
            output_path: Local path to save the backup file

        Raises:
            APIError: If download fails
        """
        # Use a direct download approach
        import requests
        from pathlib import Path

        url = f"{self.base_url.rstrip('/')}/api/v1/system/backups/{backup_id}/download"
        headers = {"X-API-Key": self.api_key}

        response = requests.get(url, headers=headers, stream=True, timeout=300)
        response.raise_for_status()

        output_file = Path(output_path)
        with open(output_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def restore_backup(self, backup_id: int) -> dict[str, Any]:
        """Restore the database from a backup.

        This is a destructive operation that will replace the current database.

        Args:
            backup_id: Database ID of the backup to restore

        Returns:
            Restore result message
        """
        return self.post(f"system/backups/{backup_id}/restore")

    def delete_backup(self, backup_id: int) -> dict[str, Any]:
        """Delete a backup.

        Args:
            backup_id: Database ID of the backup to delete

        Returns:
            Delete result message
        """
        return self.delete(f"system/backups/{backup_id}")

    # ============================================================================
    # AGENTS METHODS
    # ============================================================================

    def get_global_agent_context(self) -> dict[str, Any]:
        """Get the global agent context.

        Returns:
            Global agent context data including content and metadata
        """
        return self.get("agents/global")

    def set_global_agent_context(self, content: str) -> dict[str, Any]:
        """Set or update the global agent context.

        Args:
            content: The global AGENTS.md content

        Returns:
            Updated global agent context data
        """
        return self.put("agents/global", json={"content": content})

    def delete_global_agent_context(self) -> dict[str, Any]:
        """Delete the global agent context.

        Returns:
            Deletion confirmation message
        """
        return self.delete("agents/global")

    def get_global_agents_history(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get version history for global agent context.

        Args:
            limit: Maximum number of versions to return
            offset: Number of versions to skip

        Returns:
            Version history data with list of versions
        """
        return self.get("agents/global/history", params={"limit": limit, "offset": offset})

    def get_global_agents_version(self, version_number: int) -> dict[str, Any]:
        """Get a specific version of global agent context.

        Args:
            version_number: The version number to retrieve

        Returns:
            Version data including full content
        """
        return self.get(f"agents/global/history/{version_number}")

    def rollback_global_agents_context(
        self, version_number: int, description: Optional[str] = None
    ) -> dict[str, Any]:
        """Rollback global agent context to a previous version.

        Args:
            version_number: The version number to rollback to
            description: Optional description for the rollback

        Returns:
            Updated global agent context data
        """
        payload = {}
        if description:
            payload["description"] = description
        return self.post(
            f"agents/global/rollback/{version_number}",
            json=payload if payload else None
        )

    def get_global_agents_diff(
        self, from_version: int, to_version: int
    ) -> dict[str, Any]:
        """Get diff between two versions of global agent context.

        Args:
            from_version: Source version number
            to_version: Target version number

        Returns:
            Diff data with unified diff text and statistics
        """
        return self.get(
            "agents/global/diff",
            params={"from": from_version, "to": to_version}
        )

    # ============================================================================
    # ISSUE PLAN METHODS
    # ============================================================================

    def get_issue_plan(self, issue_id: int) -> dict[str, Any]:
        """Get the implementation plan for an issue.

        Args:
            issue_id: The database ID of the issue

        Returns:
            Plan data including content, status, and metadata
        """
        return self.get(f"issues/{issue_id}/plan")

    def create_or_update_issue_plan(
        self, issue_id: int, content: str, status: str = "draft"
    ) -> dict[str, Any]:
        """Create or update the implementation plan for an issue.

        Args:
            issue_id: The database ID of the issue
            content: The markdown content of the plan
            status: Status of the plan (draft, approved, in_progress, completed)

        Returns:
            Plan data including content, status, and metadata
        """
        return self.post(
            f"issues/{issue_id}/plan", json={"content": content, "status": status}
        )

    def delete_issue_plan(self, issue_id: int) -> dict[str, Any]:
        """Delete the implementation plan for an issue.

        Args:
            issue_id: The database ID of the issue

        Returns:
            Deletion confirmation message
        """
        return self.delete(f"issues/{issue_id}/plan")
