"""System status monitoring service for aiops core components."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy import text

from ..extensions import db


def check_database() -> dict[str, Any]:
    """Check database connectivity and health.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        # Test database connection with a simple query
        result = db.session.execute(text("SELECT 1")).scalar()
        if result == 1:
            # Get database file info
            db_path = current_app.config.get("SQLALCHEMY_DATABASE_URI", "").replace("sqlite:///", "")
            if db_path and Path(db_path).exists():
                size_mb = Path(db_path).stat().st_size / (1024 * 1024)
                return {
                    "healthy": True,
                    "message": "Database connected",
                    "details": {
                        "path": db_path,
                        "size_mb": round(size_mb, 2),
                    }
                }
            return {"healthy": True, "message": "Database connected"}
        return {"healthy": False, "message": "Database query failed"}
    except Exception as exc:  # noqa: BLE001
        return {
            "healthy": False,
            "message": f"Database error: {exc}",
            "details": {"error": str(exc)}
        }


def check_tmux_server() -> dict[str, Any]:
    """Check if tmux server is running.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            sessions = [s for s in result.stdout.strip().split("\n") if s]
            return {
                "healthy": True,
                "message": f"Tmux server running with {len(sessions)} session(s)",
                "details": {"session_count": len(sessions)}
            }
        # No sessions but server might be running
        if "no server running" in result.stderr:
            return {
                "healthy": True,
                "message": "Tmux server available (no sessions)",
                "details": {"session_count": 0}
            }
        return {
            "healthy": False,
            "message": "Tmux server not responding",
            "details": {"stderr": result.stderr}
        }
    except subprocess.TimeoutExpired:
        return {"healthy": False, "message": "Tmux server timeout"}
    except FileNotFoundError:
        return {"healthy": False, "message": "Tmux not installed"}
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Tmux error: {exc}"}


def check_git() -> dict[str, Any]:
    """Check if git and CLI tools (gh, glab) are available.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    tools_status = {}

    # Check git
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            tools_status["git"] = {"available": True, "version": version}
        else:
            tools_status["git"] = {"available": False, "error": "Command failed"}
    except FileNotFoundError:
        tools_status["git"] = {"available": False, "error": "Not installed"}
    except Exception as exc:  # noqa: BLE001
        tools_status["git"] = {"available": False, "error": str(exc)}

    # Check gh (GitHub CLI)
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip().split("\n")[0]  # First line has version
            tools_status["gh"] = {"available": True, "version": version}
        else:
            tools_status["gh"] = {"available": False, "error": "Command failed"}
    except FileNotFoundError:
        tools_status["gh"] = {"available": False, "error": "Not installed"}
    except Exception as exc:  # noqa: BLE001
        tools_status["gh"] = {"available": False, "error": str(exc)}

    # Check glab (GitLab CLI)
    try:
        result = subprocess.run(
            ["glab", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            tools_status["glab"] = {"available": True, "version": version}
        else:
            tools_status["glab"] = {"available": False, "error": "Command failed"}
    except FileNotFoundError:
        tools_status["glab"] = {"available": False, "error": "Not installed"}
    except Exception as exc:  # noqa: BLE001
        tools_status["glab"] = {"available": False, "error": str(exc)}

    # Determine overall health - git is required, gh/glab are optional
    git_available = tools_status.get("git", {}).get("available", False)
    available_count = sum(1 for t in tools_status.values() if t.get("available", False))
    total_count = len(tools_status)

    return {
        "healthy": git_available,
        "message": f"{available_count}/{total_count} Git tools available",
        "details": {"tools": tools_status}
    }


def check_ai_tools() -> dict[str, Any]:
    """Check availability of AI tools (Claude, Codex, Gemini) and Ollama.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    import os
    tools_config = current_app.config.get("ALLOWED_AI_TOOLS", {})
    tools_status = {}

    # Add common binary locations to PATH for checking
    extra_paths = ["/usr/local/bin", "/usr/bin", "/bin"]
    current_path = os.environ.get("PATH", "")
    search_path = current_path
    for extra in extra_paths:
        if extra not in current_path:
            search_path = f"{extra}:{search_path}"

    for tool_name, tool_command in tools_config.items():
        if tool_name == "shell":
            continue  # Skip shell check

        # Extract binary name from command
        binary = tool_command.split()[0] if tool_command else tool_name

        # Check with extended PATH
        found_path = shutil.which(binary, path=search_path)
        if found_path:
            tools_status[tool_name] = {"available": True, "path": found_path}
        else:
            tools_status[tool_name] = {"available": False, "path": None}

    # Special handling for Ollama (Python API, not CLI binary)
    try:
        from app.services.ollama_service import check_ollama_health
        is_healthy, error_msg = check_ollama_health()
        if is_healthy:
            api_url = current_app.config.get("OLLAMA_API_URL", "http://localhost:11434")
            model = current_app.config.get("OLLAMA_MODEL", "qwen2.5:7b")
            tools_status["ollama"] = {
                "available": True,
                "api_url": api_url,
                "model": model,
            }
        else:
            tools_status["ollama"] = {
                "available": False,
                "error": error_msg,
            }
    except Exception as exc:
        tools_status["ollama"] = {
            "available": False,
            "error": f"Error checking Ollama: {exc}",
        }

    available_count = sum(1 for t in tools_status.values() if t["available"])
    total_count = len(tools_status)

    return {
        "healthy": available_count > 0,
        "message": f"{available_count}/{total_count} AI tools available",
        "details": {"tools": tools_status}
    }


def check_workspaces() -> dict[str, Any]:
    """Check workspace directory accessibility.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        instance_path = Path(current_app.instance_path)

        # Check instance directory
        if not instance_path.exists():
            return {
                "healthy": False,
                "message": "Instance directory missing",
                "details": {"path": str(instance_path)}
            }

        # Check workspace directories
        workspace_dirs = list(instance_path.glob("workspaces/*"))

        # Check session pipes
        pipes_dir = instance_path / "session_pipes"
        pipes_exist = pipes_dir.exists()
        pipe_count = len(list(pipes_dir.glob("*.log"))) if pipes_exist else 0

        return {
            "healthy": True,
            "message": "Workspace accessible",
            "details": {
                "instance_path": str(instance_path),
                "workspace_count": len(workspace_dirs),
                "session_pipes": pipe_count,
            }
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Workspace error: {exc}"}


def check_integrations() -> dict[str, Any]:
    """Check issue tracker integrations status.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        from ..models import TenantIntegration

        integrations = TenantIntegration.query.all()

        if not integrations:
            return {
                "healthy": True,
                "message": "No integrations configured",
                "details": {"count": 0}
            }

        integration_status = {}
        for integration in integrations:
            integration_status[integration.name] = {
                "provider": integration.provider,
                "enabled": integration.enabled,
            }

        enabled_count = sum(1 for i in integrations if i.enabled)

        return {
            "healthy": True,
            "message": f"{enabled_count}/{len(integrations)} integrations enabled",
            "details": {"integrations": integration_status}
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Integration check error: {exc}"}


def check_cli_git_tools() -> dict[str, Any]:
    """Check GitHub (gh) and GitLab (glab) CLI tools authentication.

    Tests authentication with configured PATs for each tenant integration.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        from ..models import TenantIntegration

        integrations = TenantIntegration.query.filter(
            TenantIntegration.provider.in_(["github", "gitlab"])
        ).all()

        if not integrations:
            return {
                "healthy": True,
                "message": "No GitHub/GitLab integrations configured",
                "details": {"integrations": []}
            }

        integration_checks = []
        auth_failures = 0

        for integration in integrations:
            # Determine which token is being used
            token = integration.api_token or integration.access_token
            token_source = "tenant"
            token_preview = None

            # Check if there's a project-level override
            # Note: We check all projects for this integration to see if any have overrides
            from ..models import ProjectIntegration
            project_overrides = ProjectIntegration.query.filter_by(
                integration_id=integration.id
            ).filter(
                ProjectIntegration.override_api_token.isnot(None)
            ).all()

            if project_overrides:
                token_source = f"project-override ({len(project_overrides)} project(s))"

            if token:
                # Show first 10 and last 4 characters of token
                if len(token) > 20:
                    token_preview = f"{token[:10]}...{token[-4:]}"
                else:
                    token_preview = f"{token[:10]}..."

            check_result = {
                "integration_id": integration.id,
                "name": integration.name,
                "provider": integration.provider,
                "tenant_name": integration.tenant.name if integration.tenant else None,
                "has_token": bool(token),
                "token_source": token_source,
                "token_preview": token_preview,
                "auth_ok": False,
                "error": None,
            }

            # Skip if no token
            if not token:
                check_result["error"] = "No access token configured"
                integration_checks.append(check_result)
                auth_failures += 1
                continue

            # Test authentication based on provider
            if integration.provider == "github":
                auth_ok, error = _test_github_auth(integration)
                check_result["auth_ok"] = auth_ok
                check_result["error"] = error
                if not auth_ok:
                    auth_failures += 1
            elif integration.provider == "gitlab":
                auth_ok, error = _test_gitlab_auth(integration)
                check_result["auth_ok"] = auth_ok
                check_result["error"] = error
                if not auth_ok:
                    auth_failures += 1

            integration_checks.append(check_result)

        total = len(integration_checks)
        passed = total - auth_failures

        return {
            "healthy": auth_failures == 0,
            "message": f"{passed}/{total} CLI git integrations authenticated",
            "details": {"integrations": integration_checks}
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"CLI git tools check error: {exc}"}


def _test_github_auth(integration: Any) -> tuple[bool, str | None]:
    """Test GitHub CLI (gh) authentication.

    Args:
        integration: TenantIntegration with GitHub provider

    Returns:
        Tuple of (auth_ok, error_message)
    """
    try:
        import os

        token = integration.api_token or integration.access_token
        if not token:
            return False, "No token available"

        # Set up environment
        env = os.environ.copy()
        env["GH_TOKEN"] = token

        # Add GH_HOST for GitHub Enterprise
        base_url = getattr(integration, "base_url", None)
        if base_url and "github.com" not in base_url:
            env["GH_HOST"] = base_url

        # Test authentication with gh auth status
        result = subprocess.run(
            ["gh", "auth", "status"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        # gh auth status returns 0 when authenticated
        if result.returncode == 0:
            return True, None

        # Extract error from stderr
        error_msg = result.stderr.strip() if result.stderr else "Authentication failed"
        return False, error_msg

    except FileNotFoundError:
        return False, "gh CLI not installed"
    except subprocess.TimeoutExpired:
        return False, "Authentication check timeout"
    except Exception as exc:  # noqa: BLE001
        return False, f"Check failed: {exc}"


def _test_gitlab_auth(integration: Any) -> tuple[bool, str | None]:
    """Test GitLab CLI (glab) authentication via API call.

    Tests authentication the same way AI tool sessions use it - with GITLAB_TOKEN
    environment variable. Uses glab api command to verify token validity.

    Args:
        integration: TenantIntegration with GitLab provider

    Returns:
        Tuple of (auth_ok, error_message)
    """
    try:
        import os
        from urllib.parse import urlparse

        token = integration.api_token or integration.access_token
        if not token:
            return False, "No token available"

        # Set up environment - same as AI tool sessions
        env = os.environ.copy()
        env["GITLAB_TOKEN"] = token

        # Determine hostname for private instances
        base_url = getattr(integration, "base_url", None)
        hostname = None
        if base_url and "gitlab.com" not in base_url:
            # Extract hostname from URL (e.g., "gitlab.kumbe.it" from "https://gitlab.kumbe.it")
            parsed = urlparse(base_url)
            hostname = parsed.netloc or parsed.path.strip("/")
            env["GITLAB_HOST"] = base_url

        # Test authentication with glab api call to /user endpoint
        # This mimics how git operations work in AI tool sessions
        if hostname:
            result = subprocess.run(
                ["glab", "api", "user", "--hostname", hostname],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            result = subprocess.run(
                ["glab", "api", "user"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

        # glab api returns 0 on success
        if result.returncode == 0:
            return True, None

        # Extract error from stderr
        error_msg = result.stderr.strip() if result.stderr else "Authentication failed"
        # Simplify error message if it's too long
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        return False, error_msg

    except FileNotFoundError:
        return False, "glab CLI not installed"
    except subprocess.TimeoutExpired:
        return False, "Authentication check timeout"
    except Exception as exc:  # noqa: BLE001
        return False, f"Check failed: {exc}"


def check_ssh_connectivity() -> dict[str, Any]:
    """Check SSH connectivity to each project's Git repository.

    Tests SSH connectivity using configured tenant SSH keys.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        from ..models import Project
        from urllib.parse import urlparse

        # Get all projects that use SSH URLs (git@... or ssh://...)
        projects = Project.query.all()
        ssh_projects = [
            p for p in projects
            if p.repo_url and (
                p.repo_url.startswith("git@") or
                p.repo_url.startswith("ssh://")
            )
        ]

        if not ssh_projects:
            return {
                "healthy": True,
                "message": "No SSH-based Git projects configured",
                "details": {"projects": []}
            }

        project_checks = []
        connectivity_failures = 0

        for project in ssh_projects:
            # Extract hostname and port from Git URL
            hostname = None
            port = None
            if project.repo_url.startswith("git@"):
                # Format: git@hostname:owner/repo.git or git@hostname:port:owner/repo.git
                after_at = project.repo_url.split("@")[1]
                first_colon_part = after_at.split(":")[0]

                # Check if there's a port (hostname:port:path vs hostname:path)
                # If first part after : is a number, it's a port
                parts_after_host = after_at.split(":", 1)[1] if ":" in after_at else ""
                if parts_after_host and ":" in parts_after_host:
                    # Format: git@hostname:port:path
                    first_path_part = parts_after_host.split(":")[0]
                    if first_path_part.isdigit():
                        hostname = first_colon_part
                        port = int(first_path_part)
                    else:
                        hostname = first_colon_part
                else:
                    hostname = first_colon_part
            elif project.repo_url.startswith("ssh://"):
                # Format: ssh://git@hostname:port/owner/repo.git
                parsed = urlparse(project.repo_url)
                hostname = parsed.hostname
                port = parsed.port

            if not hostname:
                project_checks.append({
                    "project_id": project.id,
                    "project_name": project.name,
                    "tenant_name": project.tenant.name if project.tenant else "Unknown",
                    "hostname": None,
                    "ssh_ok": False,
                    "error": "Could not parse hostname from repo URL"
                })
                connectivity_failures += 1
                continue

            # Test SSH connectivity
            display_host = f"{hostname}:{port}" if port else hostname
            ssh_ok, error, key_info = _test_ssh_connectivity(project, hostname, port)

            project_checks.append({
                "project_id": project.id,
                "project_name": project.name,
                "tenant_name": project.tenant.name if project.tenant else "Unknown",
                "hostname": display_host,
                "ssh_ok": ssh_ok,
                "error": error,
                "ssh_key": key_info,
            })

            if not ssh_ok:
                connectivity_failures += 1

        total = len(project_checks)
        passed = total - connectivity_failures

        return {
            "healthy": connectivity_failures == 0,
            "message": f"{passed}/{total} SSH connections OK",
            "details": {"projects": project_checks}
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"SSH connectivity check error: {exc}"}


def _test_ssh_connectivity(project: Any, hostname: str, port: int | None = None) -> tuple[bool, str | None, dict | None]:
    """Test SSH connectivity to a Git host using project's SSH key.

    Args:
        project: Project with SSH key configuration
        hostname: Git host to test (e.g., "github.com", "gitlab.com")
        port: Optional SSH port (defaults to 22 if not specified)

    Returns:
        Tuple of (ssh_ok, error_message, key_info_dict)
    """
    try:
        from ..services.git_service import _select_project_ssh_key
        from ..services.ssh_key_service import ssh_key_context

        # Get SSH key for project
        key_path, key_model, key_source = _select_project_ssh_key(project)

        # Build key info dict
        key_info = None
        if key_model:
            key_info = {
                "name": key_model.name,
                "source": key_source,
                "storage": "database" if key_model.encrypted_private_key else "filesystem",
            }
        elif key_path:
            # Filesystem key without model
            key_info = {
                "name": key_path.split("/")[-1] if "/" in key_path else key_path,
                "source": key_source,
                "storage": "filesystem",
            }

        # No SSH key configured
        if not key_path and not (key_model and key_model.encrypted_private_key):
            return False, "No SSH key configured", None

        # Build SSH command to test connectivity
        # Use -T (disable pseudo-terminal) and -o BatchMode=yes (non-interactive)
        # This will connect and immediately disconnect, testing authentication

        # Build SSH command with optional port
        ssh_args_base = [
            "ssh",
            "-T",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
        ]

        # Add port if specified
        if port:
            ssh_args_base.extend(["-p", str(port)])

        if key_model and key_model.encrypted_private_key:
            # Use database key with ssh_key_context
            try:
                with ssh_key_context(key_model.encrypted_private_key) as auth_sock:
                    env = {
                        "SSH_AUTH_SOCK": auth_sock,
                    }
                    ssh_args = ssh_args_base + [f"git@{hostname}"]
                    result = subprocess.run(
                        ssh_args,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
            except Exception as exc:
                return False, f"Database key error: {exc}", key_info
        else:
            # Use filesystem key
            ssh_args = ssh_args_base + [
                "-i", key_path,
                "-o", "IdentitiesOnly=yes",
                f"git@{hostname}",
            ]
            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=15,
            )

        # SSH to Git hosts typically returns exit code 1 with a success message
        # GitHub: "Hi username! You've successfully authenticated..."
        # GitLab: "Welcome to GitLab, @username!"
        # BitBucket: "authenticated via ssh key"

        stdout = result.stdout.lower()
        stderr = result.stderr.lower()
        output = stdout + stderr

        # Check for success indicators
        if any(indicator in output for indicator in [
            "successfully authenticated",
            "welcome to gitlab",
            "authenticated via",
            "you've successfully",
            "shell request failed",  # Azure DevOps - auth OK but no shell
        ]):
            return True, None, key_info

        # Check for specific error conditions
        if "permission denied" in output:
            return False, "Permission denied (key not authorized)", key_info
        if "connection refused" in output:
            return False, "Connection refused", key_info
        if "timeout" in output or "timed out" in output:
            return False, "Connection timeout", key_info
        if "could not resolve hostname" in output:
            return False, "Could not resolve hostname", key_info

        # If we got here, SSH connected but authentication status is unclear
        # Exit code 1 with output typically means success for Git hosts
        if result.returncode == 1 and output:
            return True, None, key_info

        # Unknown response
        error_msg = (stderr or stdout or "Unknown SSH response").strip()
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."
        return False, error_msg, key_info

    except subprocess.TimeoutExpired:
        return False, "SSH connection timeout", None
    except Exception as exc:  # noqa: BLE001
        return False, f"Check failed: {exc}", None


def check_sessions() -> dict[str, Any]:
    """Check active AI sessions.

    Returns:
        Status dict with 'healthy', 'message', and 'details'
    """
    try:
        from ..models import AISession as AISessionModel

        active_sessions = AISessionModel.query.filter_by(is_active=True).all()

        session_details = {
            "total_active": len(active_sessions),
            "by_tool": {},
        }

        for session in active_sessions:
            tool = session.tool or "unknown"
            session_details["by_tool"][tool] = session_details["by_tool"].get(tool, 0) + 1

        return {
            "healthy": True,
            "message": f"{len(active_sessions)} active session(s)",
            "details": session_details
        }
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "message": f"Session check error: {exc}"}


def get_system_status() -> dict[str, Any]:
    """Get comprehensive system status for all components.

    Returns:
        Dictionary with overall status and individual component statuses
    """
    components = {
        "database": check_database(),
        "tmux": check_tmux_server(),
        "git": check_git(),
        "ai_tools": check_ai_tools(),
        "workspaces": check_workspaces(),
        "integrations": check_integrations(),
        "cli_git_tools": check_cli_git_tools(),
        "ssh_connectivity": check_ssh_connectivity(),
        "sessions": check_sessions(),
    }

    # Calculate overall health
    all_healthy = all(comp.get("healthy", False) for comp in components.values())
    unhealthy_count = sum(1 for comp in components.values() if not comp.get("healthy", False))

    return {
        "healthy": all_healthy,
        "timestamp": datetime.utcnow().isoformat(),
        "components": components,
        "summary": {
            "total_components": len(components),
            "healthy_components": len(components) - unhealthy_count,
            "unhealthy_components": unhealthy_count,
        }
    }
