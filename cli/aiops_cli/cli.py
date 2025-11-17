"""Main CLI entry point for AIops CLI."""

import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .client import APIClient, APIError
from .config import Config
from .output import format_output

console = Console()
error_console = Console(stderr=True)


def get_client(ctx: click.Context) -> APIClient:
    """Get configured API client.

    Args:
        ctx: Click context

    Returns:
        APIClient instance

    Raises:
        click.ClickException: If client is not configured
    """
    config: Config = ctx.obj["config"]

    url = config.url
    api_key = config.api_key

    if not url:
        raise click.ClickException(
            "API URL not configured. Run: aiops config set url <url>"
        )
    if not api_key:
        raise click.ClickException(
            "API key not configured. Run: aiops config set api_key <key>"
        )

    return APIClient(url, api_key)


def resolve_project_id(client: APIClient, project_identifier: str) -> int:
    """Resolve project name or ID to numeric ID.

    Args:
        client: API client
        project_identifier: Project ID (numeric string) or name

    Returns:
        Project ID as integer

    Raises:
        click.ClickException: If project not found or multiple matches
    """
    # Check if it's a numeric ID
    if project_identifier.isdigit():
        return int(project_identifier)

    # Look up project by name (case-insensitive)
    projects = client.list_projects()
    matching_projects = [
        p for p in projects if p.get("name", "").lower() == project_identifier.lower()
    ]

    if not matching_projects:
        raise click.ClickException(f"Project '{project_identifier}' not found")

    if len(matching_projects) > 1:
        error_console.print(
            f"[yellow]Warning:[/yellow] Multiple projects named '{project_identifier}' found, using first match",
        )

    return matching_projects[0]["id"]


def resolve_tenant_id(client: APIClient, tenant_identifier: str) -> int:
    """Resolve tenant name or ID to numeric ID.

    Args:
        client: API client
        tenant_identifier: Tenant ID (numeric string), name, or slug

    Returns:
        Tenant ID as integer

    Raises:
        click.ClickException: If tenant not found or multiple matches
    """
    # Check if it's a numeric ID
    if tenant_identifier.isdigit():
        return int(tenant_identifier)

    # Look up tenant by name or slug (case-insensitive)
    tenants = client.list_tenants()
    matching_tenants = [
        t for t in tenants if (
            t.get("name", "").lower() == tenant_identifier.lower()
            or t.get("slug", "").lower() == tenant_identifier.lower()
        )
    ]

    if not matching_tenants:
        raise click.ClickException(f"Tenant '{tenant_identifier}' not found")

    if len(matching_tenants) > 1:
        error_console.print(
            f"[yellow]Warning:[/yellow] Multiple tenants matching '{tenant_identifier}' found, using first match",
        )

    return matching_tenants[0]["id"]


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """AIops CLI - Command-line interface for AIops REST API."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config()
    ctx.obj["console"] = console


# ============================================================================
# AUTH COMMANDS
# ============================================================================


@cli.group()
def auth() -> None:
    """Authentication commands."""


@auth.command(name="whoami")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def auth_whoami(ctx: click.Context, output: Optional[str]) -> None:
    """Show current user information."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        user = client.whoami()
        format_output(user, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@auth.group(name="keys")
def auth_keys() -> None:
    """Manage API keys."""


@auth_keys.command(name="list")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def auth_keys_list(ctx: click.Context, output: Optional[str]) -> None:
    """List API keys."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        keys = client.list_api_keys()
        format_output(keys, output_format, console, title="API Keys")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@auth_keys.command(name="create")
@click.option("--name", required=True, help="Key name")
@click.option(
    "--scopes",
    required=True,
    help="Comma-separated scopes (read, write, admin)",
)
@click.option("--expires-days", type=int, help="Days until expiration")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def auth_keys_create(
    ctx: click.Context,
    name: str,
    scopes: str,
    expires_days: Optional[int],
    output: Optional[str],
) -> None:
    """Create new API key."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    scope_list = [s.strip() for s in scopes.split(",")]

    try:
        key_data = client.create_api_key(name, scope_list, expires_days)
        console.print("[green]API key created successfully![/green]")
        console.print(f"\n[yellow]API Key:[/yellow] {key_data.get('key')}")
        console.print("[yellow]Save this key - it won't be shown again![/yellow]\n")
        format_output(key_data, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@auth_keys.command(name="delete")
@click.argument("key_id", type=int)
@click.pass_context
def auth_keys_delete(ctx: click.Context, key_id: int) -> None:
    """Delete API key."""
    client = get_client(ctx)

    try:
        client.delete_api_key(key_id)
        console.print(f"[green]API key {key_id} deleted successfully![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# ISSUES COMMANDS
# ============================================================================


@cli.group()
def issues() -> None:
    """Issue management commands."""


@issues.command(name="pin")
@click.argument("issue_id", type=int)
@click.pass_context
def issues_pin(ctx: click.Context, issue_id: int) -> None:
    """Pin an issue for quick access."""
    client = get_client(ctx)

    try:
        result = client.pin_issue(issue_id)
        console.print(f"[green]✓[/green] {result.get('message', 'Issue pinned successfully')}")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="unpin")
@click.argument("issue_id", type=int)
@click.pass_context
def issues_unpin(ctx: click.Context, issue_id: int) -> None:
    """Unpin an issue."""
    client = get_client(ctx)

    try:
        result = client.unpin_issue(issue_id)
        console.print(f"[green]✓[/green] {result.get('message', 'Issue unpinned successfully')}")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="pinned")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def issues_pinned(ctx: click.Context, output: Optional[str]) -> None:
    """List your pinned issues."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        pinned_issues = client.list_pinned_issues()

        if not pinned_issues:
            console.print("[yellow]No pinned issues found[/yellow]")
            return

        # Show relevant columns for pinned issues
        columns = ["id", "external_id", "title", "status_label", "project_name"]
        format_output(pinned_issues, output_format, console, title="Pinned Issues", columns=columns)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="list")
@click.option("--status", help="Filter by status (open, closed)")
@click.option("--provider", help="Filter by provider (github, gitlab, jira)")
@click.option("--project", help="Filter by project ID or name")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def issues_list(
    ctx: click.Context,
    status: Optional[str],
    provider: Optional[str],
    project: Optional[str],
    limit: Optional[int],
    output: Optional[str],
) -> None:
    """List issues."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        # Resolve project name to ID if needed
        project_id = None
        if project:
            project_id = resolve_project_id(client, project)

        issues_data = client.list_issues(
            status=status,
            provider=provider,
            project_id=project_id,
            limit=limit,
        )
        # Show only the most relevant columns for list view
        columns = ["id", "external_id", "title", "status", "provider", "project_name", "assignee"]
        format_output(issues_data, output_format, console, title="Issues", columns=columns)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="get")
@click.argument("issue_id", type=int)
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def issues_get(ctx: click.Context, issue_id: int, output: Optional[str]) -> None:
    """Get issue details."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        issue = client.get_issue(issue_id)
        format_output(issue, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="create")
@click.option("--project", required=True, help="Project ID or name")
@click.option("--integration", type=int, required=True, help="Integration ID")
@click.option("--title", required=True, help="Issue title")
@click.option("--description", help="Issue description")
@click.option("--labels", help="Comma-separated labels")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def issues_create(
    ctx: click.Context,
    project: str,
    integration: int,
    title: str,
    description: Optional[str],
    labels: Optional[str],
    output: Optional[str],
) -> None:
    """Create new issue."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    label_list = [label.strip() for label in labels.split(",")] if labels else None

    try:
        project_id = resolve_project_id(client, project)
        issue = client.create_issue(project_id, integration, title, description, label_list)
        console.print("[green]Issue created successfully![/green]")
        format_output(issue, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="update")
@click.argument("issue_id", type=int)
@click.option("--title", help="New title")
@click.option("--description", help="New description")
@click.option("--labels", help="Comma-separated labels")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def issues_update(
    ctx: click.Context,
    issue_id: int,
    title: Optional[str],
    description: Optional[str],
    labels: Optional[str],
    output: Optional[str],
) -> None:
    """Update issue."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    label_list = [label.strip() for label in labels.split(",")] if labels else None

    try:
        issue = client.update_issue(issue_id, title, description, label_list)
        console.print("[green]Issue updated successfully![/green]")
        format_output(issue, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="close")
@click.argument("issue_id", type=int)
@click.pass_context
def issues_close(ctx: click.Context, issue_id: int) -> None:
    """Close issue."""
    client = get_client(ctx)

    try:
        client.close_issue(issue_id)
        console.print(f"[green]Issue {issue_id} closed successfully![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="comment")
@click.argument("issue_id", type=int)
@click.argument("body")
@click.option("--no-mention-resolve", is_flag=True, help="Disable automatic @mention resolution")
@click.pass_context
def issues_comment(ctx: click.Context, issue_id: int, body: str, no_mention_resolve: bool) -> None:
    """Add comment to issue.

    Automatically resolves @mentions to Jira account IDs by looking up users
    from the issue's comment history.

    Examples:
        aiops issues comment 254 "@jens Thanks for the info!"
        aiops issues comment 254 '@"Jens Hassler" The tunnel is working great'
        aiops issues comment 254 "Fixed the issue" --no-mention-resolve
    """
    client = get_client(ctx)

    try:
        # Resolve @mentions unless disabled
        if not no_mention_resolve and "@" in body:
            # Fetch issue to get comments for user resolution
            issue = client.get_issue(issue_id)
            comments = issue.get("comments", [])

            if comments:
                from .mentions import resolve_mentions, extract_jira_users_from_comments

                # Build user map from comments
                user_map = extract_jira_users_from_comments(comments)

                if user_map:
                    # Resolve mentions
                    resolved_body = resolve_mentions(body, user_map)

                    # Show what was resolved if any changes were made
                    if resolved_body != body:
                        console.print("[dim]Resolved mentions:[/dim]")
                        # Show resolved users
                        for name, account_id in user_map.items():
                            if name in body.lower():
                                console.print(f"  [dim]@{name} -> accountid:{account_id}[/dim]")
                        body = resolved_body

        client.add_issue_comment(issue_id, body)
        console.print(f"[green]Comment added to issue {issue_id}![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="modify-comment")
@click.argument("issue_id", type=int)
@click.argument("comment_id")
@click.argument("body")
@click.option("--no-mention-resolve", is_flag=True, help="Disable automatic @mention resolution")
@click.pass_context
def issues_modify_comment(ctx: click.Context, issue_id: int, comment_id: str, body: str, no_mention_resolve: bool) -> None:
    """Modify an existing comment on an issue.

    Automatically resolves @mentions to Jira account IDs by looking up users
    from the issue's comment history.

    Examples:
        aiops issues modify-comment 254 12345 "@jens Updated the details!"
        aiops issues modify-comment 254 12345 "Corrected the information" --no-mention-resolve
    """
    client = get_client(ctx)

    try:
        # Resolve @mentions unless disabled
        if not no_mention_resolve and "@" in body:
            # Fetch issue to get comments for user resolution
            issue = client.get_issue(issue_id)
            comments = issue.get("comments", [])

            if comments:
                from .mentions import resolve_mentions, extract_jira_users_from_comments

                # Build user map from comments
                user_map = extract_jira_users_from_comments(comments)

                if user_map:
                    # Resolve mentions
                    resolved_body = resolve_mentions(body, user_map)

                    # Show what was resolved if any changes were made
                    if resolved_body != body:
                        console.print("[dim]Resolved mentions:[/dim]")
                        # Show resolved users
                        for name, account_id in user_map.items():
                            if name in body.lower():
                                console.print(f"  [dim]@{name} -> accountid:{account_id}[/dim]")
                        body = resolved_body

        client.update_issue_comment(issue_id, comment_id, body)
        console.print(f"[green]Comment {comment_id} on issue {issue_id} updated successfully![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="assign")
@click.argument("issue_id", type=int)
@click.option("--user", type=int, help="User ID (defaults to self)")
@click.pass_context
def issues_assign(ctx: click.Context, issue_id: int, user: Optional[int]) -> None:
    """Assign issue to user."""
    client = get_client(ctx)

    try:
        client.assign_issue(issue_id, user)
        console.print(f"[green]Issue {issue_id} assigned successfully![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="sync")
@click.option("--tenant", help="Tenant ID or slug to sync")
@click.option("--project", help="Project ID or name to sync")
@click.option("--integration", type=int, help="Integration ID to sync")
@click.option("--force-full", is_flag=True, help="Force full sync (ignore last sync time)")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def issues_sync(
    ctx: click.Context,
    tenant: Optional[str],
    project: Optional[str],
    integration: Optional[int],
    force_full: bool,
    output: Optional[str],
) -> None:
    """Synchronize issues from external providers (GitHub, GitLab, Jira).

    Examples:
        aiops issues sync                        # Sync all issues
        aiops issues sync --tenant floads        # Sync issues for a tenant
        aiops issues sync --project aiops        # Sync issues for a project
        aiops issues sync --force-full           # Force full sync
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        # Resolve tenant and project names to IDs if needed
        tenant_id = None
        project_id = None

        if tenant:
            tenant_id = resolve_tenant_id(client, tenant)
        if project:
            project_id = resolve_project_id(client, project)

        # Perform sync
        result = client.sync_issues(
            tenant_id=tenant_id,
            integration_id=integration,
            project_id=project_id,
            force_full=force_full,
        )

        # Display results
        synced = result.get("synced", 0)
        projects = result.get("projects", [])
        message = result.get("message", "")

        if synced == 0:
            console.print("[yellow]No issues synchronized[/yellow]")
            if message:
                console.print(f"[dim]{message}[/dim]")
            return

        console.print(f"[green]✓[/green] {message}")
        console.print(f"[green]Total issues synchronized:[/green] {synced}")

        if projects and output_format == "table":
            # Display project sync details in table format
            console.print()
            table = Table(title="Project Sync Details")
            table.add_column("Provider", style="cyan", no_wrap=True)
            table.add_column("Tenant", style="yellow")
            table.add_column("Project", style="magenta")
            table.add_column("Issues", style="green", justify="right")

            for proj in projects:
                table.add_row(
                    proj.get("provider", ""),
                    proj.get("tenant_name", ""),
                    proj.get("project_name", ""),
                    str(proj.get("issues_synced", 0)),
                )

            console.print(table)
        elif projects:
            # Use standard format_output for JSON/YAML
            format_output(projects, output_format, console, title="Project Sync Details")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="sessions")
@click.option("--project", help="Filter by project ID or name")
@click.pass_context
def issues_sessions(ctx: click.Context, project: Optional[str]) -> None:
    """List active AI sessions."""
    client = get_client(ctx)

    try:
        all_sessions = []

        if project:
            # Single project - resolve name to ID if needed
            project_id = resolve_project_id(client, project)
            sessions = client.list_ai_sessions(project_id)
            # Add project info to each session
            for session in sessions:
                session["project_id"] = project_id
            all_sessions.extend(sessions)
        else:
            # No project specified - fetch sessions from all projects
            projects = client.list_projects()
            for proj in projects:
                proj_id = proj["id"]
                sessions = client.list_ai_sessions(proj_id)
                # Add project info to each session
                for session in sessions:
                    session["project_id"] = proj_id
                    session["project_name"] = proj["name"]
                all_sessions.extend(sessions)

        if not all_sessions:
            console.print("[yellow]No active AI sessions found[/yellow]")
            return

        # Display sessions in a table
        title = f"Active AI Sessions (Project {project})" if project else "Active AI Sessions (All Projects)"
        table = Table(title=title)
        table.add_column("Session ID", style="cyan", no_wrap=True, width=15)
        table.add_column("Issue", style="magenta", no_wrap=True, width=8)
        table.add_column("Tool", style="green", no_wrap=True, width=10)
        if not project:
            # Show project name when listing all sessions
            table.add_column("Project", style="yellow", no_wrap=True, width=12)
        table.add_column("Tmux Target", style="blue", overflow="fold")

        for session in all_sessions:
            session_id = session.get("session_id", "")[:12] + "..."  # Truncate
            issue_id = str(session.get("issue_id") or "-")
            command = session.get("command", "")
            # Extract tool name from command
            tool_name = "unknown"
            if "claude" in command.lower():
                tool_name = "claude"
            elif "codex" in command.lower():
                tool_name = "codex"
            elif "gemini" in command.lower():
                tool_name = "gemini"
            tmux_target = session.get("tmux_target", "")

            if project:
                table.add_row(session_id, issue_id, tool_name, tmux_target)
            else:
                project_name = session.get("project_name", str(session.get("project_id", "-")))
                table.add_row(session_id, issue_id, tool_name, project_name, tmux_target)

        console.print(table)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="work")
@click.argument("issue_id", type=int)
@click.option("--tool", type=click.Choice(["claude", "codex", "gemini"]), help="AI tool to use")
@click.option("--prompt", help="Initial prompt to send to the AI")
@click.option("--attach", is_flag=True, help="Attach to tmux session after starting")
@click.pass_context
def issues_work(
    ctx: click.Context,
    issue_id: int,
    tool: Optional[str],
    prompt: Optional[str],
    attach: bool,
) -> None:
    """Start an AI session to work on an issue.

    This command:
    1. Claims the issue (assigns it to you)
    2. Starts an AI tool session in tmux
    3. Optionally attaches you directly to the tmux session

    Example:
        aiops issues work 123 --tool claude --attach
        aiops issues work 456 --tool codex --prompt "Fix the authentication bug"
    """
    client = get_client(ctx)

    try:
        # Start AI session on the issue
        result = client.start_ai_session_on_issue(issue_id, tool=tool, prompt=prompt)

        session_id = result.get("session_id")
        workspace_path = result.get("workspace_path")
        ssh_user = result.get("ssh_user")  # System user running Flask app (owns tmux)
        tmux_target = result.get("tmux_target")  # Actual tmux session:window to attach to
        is_existing = result.get("existing", False)  # Whether reusing existing session
        context_populated = result.get("context_populated", False)  # Whether AGENTS.override.md was populated
        warning = result.get("warning")  # Optional warning from claim-issue

        console.print(f"[green]✓[/green] Issue {issue_id} claimed successfully!")
        if warning:
            console.print(f"[yellow]⚠[/yellow] {warning}")
        if is_existing:
            console.print(f"[green]✓[/green] Reusing existing AI session (session ID: {session_id})")
        else:
            console.print(f"[green]✓[/green] AI session started (session ID: {session_id})")
        if workspace_path:
            console.print(f"[blue]Workspace:[/blue] {workspace_path}")
        if context_populated:
            console.print("[blue]Context:[/blue] AGENTS.override.md populated with issue details")

        # If attach flag is set, attach to tmux session
        if attach:
            import subprocess
            from urllib.parse import urlparse

            console.print("\n[yellow]Attaching to tmux session...[/yellow]")
            console.print("[dim]Press Ctrl+B then D to detach from tmux[/dim]\n")

            # Use tmux_target if available, otherwise fall back to session_id
            attach_target = tmux_target or session_id

            # Derive SSH host from API URL (e.g., http://dev.floads:5000 -> dev.floads)
            config: Config = ctx.obj["config"]
            api_url = config.url
            parsed_url = urlparse(api_url)
            ssh_host = parsed_url.hostname

            if not ssh_host:
                error_console.print(
                    "[red]Error:[/red] Could not derive SSH host from API URL"
                )
                error_console.print(
                    f"[yellow]You can manually attach with:[/yellow] ssh {ssh_host or 'HOST'} -t tmux attach -t {attach_target}"
                )
                sys.exit(1)

            # Build SSH target with system user running Flask app (owns tmux server)
            # e.g., syseng@dev.floads
            if ssh_user:
                ssh_target = f"{ssh_user}@{ssh_host}"
            else:
                # Fall back to just hostname if ssh_user not provided
                ssh_target = ssh_host

            # Attach to the tmux session:window
            try:
                # SSH into remote host and attach to tmux session
                subprocess.run(
                    ["ssh", "-t", ssh_target, "tmux", "attach-session", "-t", attach_target],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                error_console.print(
                    f"[red]Error attaching to tmux:[/red] {e}"
                )
                error_console.print(
                    f"[yellow]You can manually attach with:[/yellow] ssh {ssh_target} -t tmux attach -t {attach_target}"
                )
                sys.exit(1)
            except FileNotFoundError:
                error_console.print(
                    "[red]Error:[/red] ssh not found. Please install OpenSSH to use --attach"
                )
                error_console.print(
                    "[yellow]Session is running. You can access it via the web UI.[/yellow]"
                )
                sys.exit(1)
        else:
            console.print(
                f"\n[yellow]To attach to the session:[/yellow] aiops issues work {issue_id} --attach"
            )
            console.print(f"[yellow]Or use tmux:[/yellow] tmux attach -t {session_id}")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# PROJECTS COMMANDS
# ============================================================================


@cli.group()
def projects() -> None:
    """Project management commands."""


@projects.command(name="list")
@click.option("--tenant", help="Filter by tenant ID or slug")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def projects_list(ctx: click.Context, tenant: Optional[str], output: Optional[str]) -> None:
    """List projects."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        tenant_id = None
        if tenant:
            tenant_id = resolve_tenant_id(client, tenant)
        projects_data = client.list_projects(tenant_id)
        format_output(projects_data, output_format, console, title="Projects")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@projects.command(name="get")
@click.argument("project")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def projects_get(ctx: click.Context, project: str, output: Optional[str]) -> None:
    """Get project details."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        project_id = resolve_project_id(client, project)
        project_data = client.get_project(project_id)
        format_output(project_data, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@projects.command(name="create")
@click.option("--name", required=True, help="Project name")
@click.option("--repo-url", required=True, help="Repository URL")
@click.option("--tenant", required=True, help="Tenant ID or slug")
@click.option("--description", help="Project description")
@click.option("--branch", default="main", help="Default branch (default: main)")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def projects_create(
    ctx: click.Context,
    name: str,
    repo_url: str,
    tenant: str,
    description: Optional[str],
    branch: str,
    output: Optional[str],
) -> None:
    """Create new project."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        tenant_id = resolve_tenant_id(client, tenant)
        project = client.create_project(name, repo_url, tenant_id, description, branch)
        console.print("[green]Project created successfully![/green]")
        format_output(project, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@projects.command(name="status")
@click.argument("project")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def projects_status(ctx: click.Context, project: str, output: Optional[str]) -> None:
    """Get project git status."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        project_id = resolve_project_id(client, project)
        status = client.git_status(project_id)
        format_output(status, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# GIT COMMANDS
# ============================================================================


@cli.group()
def git() -> None:
    """Git operations commands."""


@git.command(name="status")
@click.argument("project")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def git_status(ctx: click.Context, project: str, output: Optional[str]) -> None:
    """Get git status."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        project_id = resolve_project_id(client, project)
        status = client.git_status(project_id)
        format_output(status, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="pull")
@click.argument("project")
@click.option("--ref", help="Branch or ref to pull")
@click.pass_context
def git_pull(ctx: click.Context, project: str, ref: Optional[str]) -> None:
    """Pull git changes."""
    client = get_client(ctx)

    try:
        project_id = resolve_project_id(client, project)
        result = client.git_pull(project_id, ref)
        console.print("[green]Pull successful![/green]")
        if result.get("message"):
            console.print(result["message"])
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="push")
@click.argument("project")
@click.option("--ref", help="Branch or ref to push")
@click.pass_context
def git_push(ctx: click.Context, project: str, ref: Optional[str]) -> None:
    """Push git changes."""
    client = get_client(ctx)

    try:
        project_id = resolve_project_id(client, project)
        result = client.git_push(project_id, ref)
        console.print("[green]Push successful![/green]")
        if result.get("message"):
            console.print(result["message"])
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="branches")
@click.argument("project")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def git_branches(ctx: click.Context, project: str, output: Optional[str]) -> None:
    """List git branches."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        project_id = resolve_project_id(client, project)
        branches = client.git_branches(project_id)
        format_output(branches, output_format, console, title="Branches")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="branch")
@click.argument("project")
@click.argument("name")
@click.option("--from", "from_branch", help="Create from branch")
@click.pass_context
def git_branch_create(
    ctx: click.Context, project: str, name: str, from_branch: Optional[str]
) -> None:
    """Create git branch."""
    client = get_client(ctx)

    try:
        project_id = resolve_project_id(client, project)
        client.git_create_branch(project_id, name, from_branch)
        console.print(f"[green]Branch '{name}' created successfully![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="checkout")
@click.argument("project")
@click.argument("branch")
@click.pass_context
def git_checkout(ctx: click.Context, project: str, branch: str) -> None:
    """Checkout git branch."""
    client = get_client(ctx)

    try:
        project_id = resolve_project_id(client, project)
        client.git_checkout(project_id, branch)
        console.print(f"[green]Checked out branch '{branch}'![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="commit")
@click.argument("project")
@click.argument("message")
@click.option("--files", help="Comma-separated list of files")
@click.pass_context
def git_commit(ctx: click.Context, project: str, message: str, files: Optional[str]) -> None:
    """Create git commit."""
    client = get_client(ctx)

    file_list = [f.strip() for f in files.split(",")] if files else None

    try:
        project_id = resolve_project_id(client, project)
        client.git_commit(project_id, message, file_list)
        console.print("[green]Commit created successfully![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="files")
@click.argument("project")
@click.option("--path", default="", help="Path to list")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def git_files(ctx: click.Context, project: str, path: str, output: Optional[str]) -> None:
    """List files in repository."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        project_id = resolve_project_id(client, project)
        files = client.git_list_files(project_id, path)
        format_output(files, output_format, console, title="Files")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="cat")
@click.argument("project")
@click.argument("file_path")
@click.pass_context
def git_cat(ctx: click.Context, project: str, file_path: str) -> None:
    """Read file from repository."""
    client = get_client(ctx)

    try:
        project_id = resolve_project_id(client, project)
        content = client.git_read_file(project_id, file_path)
        console.print(content)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# WORKFLOW COMMANDS
# ============================================================================


@cli.group()
def workflow() -> None:
    """AI workflow commands."""


@workflow.command(name="claim")
@click.argument("issue_id", type=int)
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def workflow_claim(ctx: click.Context, issue_id: int, output: Optional[str]) -> None:
    """Claim issue for work."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        result = client.workflow_claim_issue(issue_id)
        console.print(f"[green]Issue {issue_id} claimed successfully![/green]")
        format_output(result, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@workflow.command(name="progress")
@click.argument("issue_id", type=int)
@click.argument("status")
@click.option("--comment", help="Progress comment")
@click.pass_context
def workflow_progress(
    ctx: click.Context, issue_id: int, status: str, comment: Optional[str]
) -> None:
    """Update issue progress."""
    client = get_client(ctx)

    try:
        client.workflow_update_progress(issue_id, status, comment)
        console.print(f"[green]Progress updated for issue {issue_id}![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@workflow.command(name="submit")
@click.argument("issue_id", type=int)
@click.option("--project", type=int, required=True, help="Project ID")
@click.option("--message", required=True, help="Commit message")
@click.option("--files", help="Comma-separated files")
@click.option("--comment", help="Issue comment")
@click.pass_context
def workflow_submit(
    ctx: click.Context,
    issue_id: int,
    project: int,
    message: str,
    files: Optional[str],
    comment: Optional[str],
) -> None:
    """Submit changes for issue."""
    client = get_client(ctx)

    file_list = [f.strip() for f in files.split(",")] if files else None

    try:
        client.workflow_submit_changes(issue_id, project, message, file_list, comment)
        console.print(f"[green]Changes submitted for issue {issue_id}![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@workflow.command(name="approve")
@click.argument("issue_id", type=int)
@click.option("--message", help="Approval request message")
@click.pass_context
def workflow_approve(ctx: click.Context, issue_id: int, message: Optional[str]) -> None:
    """Request approval for changes."""
    client = get_client(ctx)

    try:
        client.workflow_request_approval(issue_id, message)
        console.print(f"[green]Approval requested for issue {issue_id}![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@workflow.command(name="complete")
@click.argument("issue_id", type=int)
@click.option("--summary", help="Completion summary")
@click.pass_context
def workflow_complete(ctx: click.Context, issue_id: int, summary: Optional[str]) -> None:
    """Complete issue."""
    client = get_client(ctx)

    try:
        client.workflow_complete_issue(issue_id, summary)
        console.print(f"[green]Issue {issue_id} completed successfully![/green]")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# TENANTS COMMANDS
# ============================================================================


@cli.group()
def tenants() -> None:
    """Tenant management commands."""


@tenants.command(name="list")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def tenants_list(ctx: click.Context, output: Optional[str]) -> None:
    """List tenants."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        tenants_data = client.list_tenants()
        format_output(tenants_data, output_format, console, title="Tenants")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@tenants.command(name="get")
@click.argument("tenant")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def tenants_get(ctx: click.Context, tenant: str, output: Optional[str]) -> None:
    """Get tenant details."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        tenant_id = resolve_tenant_id(client, tenant)
        tenant_data = client.get_tenant(tenant_id)
        format_output(tenant_data, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@tenants.command(name="create")
@click.option("--name", required=True, help="Tenant name")
@click.option("--description", help="Tenant description")
@click.option("--color", help="Tenant color (hex)")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def tenants_create(
    ctx: click.Context,
    name: str,
    description: Optional[str],
    color: Optional[str],
    output: Optional[str],
) -> None:
    """Create new tenant."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        tenant = client.create_tenant(name, description, color)
        console.print("[green]Tenant created successfully![/green]")
        format_output(tenant, output_format, console)
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# CONFIG COMMANDS
# ============================================================================


@cli.group()
def config() -> None:
    """Configuration management commands."""


@config.command(name="show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show current configuration."""
    config_obj: Config = ctx.obj["config"]

    table = Table(title="Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    for key, value in config_obj.all().items():
        # Mask API key for security
        if key == "api_key" and value:
            value = value[:10] + "..." + value[-4:]
        table.add_row(key, str(value))

    console.print(table)


@config.command(name="set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set configuration value."""
    config_obj: Config = ctx.obj["config"]
    config_obj.set(key, value)
    console.print(f"[green]Configuration '{key}' set successfully![/green]")


@config.command(name="get")
@click.argument("key")
@click.pass_context
def config_get(ctx: click.Context, key: str) -> None:
    """Get configuration value."""
    config_obj: Config = ctx.obj["config"]
    value = config_obj.get(key)

    if value is None:
        console.print(f"[yellow]Configuration '{key}' not set[/yellow]")
    else:
        console.print(value)


# ============================================================================
# CLI UPDATE COMMAND
# ============================================================================


@cli.command(name="update")
@click.option("--check-only", is_flag=True, help="Only check for updates without installing")
@click.pass_context
def cli_update(ctx: click.Context, check_only: bool) -> None:
    """Update the aiops CLI to the latest version.

    This command updates the aiops CLI package. For development installations,
    it will pull the latest code from git and reinstall.

    Examples:
        aiops update              # Update to latest version
        aiops update --check-only # Check for updates without installing
    """
    import subprocess
    from importlib.metadata import version, PackageNotFoundError
    from pathlib import Path

    try:
        current_version = version("aiops-cli")
    except PackageNotFoundError:
        current_version = "unknown"

    console.print(f"[blue]Current version:[/blue] {current_version}")

    # Check if this is a development/editable installation
    is_dev_install = False
    cli_path = None
    try:
        import aiops_cli
        cli_file = Path(aiops_cli.__file__)
        # If the package is in the source tree (not site-packages), it's a dev install
        if "site-packages" not in str(cli_file):
            is_dev_install = True
            # Find the CLI directory (parent of aiops_cli package)
            cli_path = cli_file.parent.parent
            console.print(f"[dim]Development installation detected at: {cli_path}[/dim]")
    except (ImportError, AttributeError):
        pass

    if check_only:
        if is_dev_install:
            console.print("[yellow]This is a development installation.[/yellow]")
            console.print("[dim]Run 'aiops update' to pull latest changes from git and reinstall.[/dim]")
        else:
            console.print("[yellow]Checking for updates...[/yellow]")
            # Try to get the latest version from PyPI
            try:
                import urllib.request
                import json
                with urllib.request.urlopen("https://pypi.org/pypi/aiops-cli/json", timeout=5) as response:
                    data = json.loads(response.read())
                    latest_version = data["info"]["version"]
                    console.print(f"[blue]Latest version:[/blue] {latest_version}")
                    if latest_version == current_version:
                        console.print("[green]✓[/green] You are running the latest version!")
                    else:
                        console.print(f"[yellow]A newer version is available: {latest_version}[/yellow]")
                        console.print("[dim]Run 'aiops update' to upgrade[/dim]")
            except Exception as e:
                console.print(f"[yellow]Could not check for updates:[/yellow] {e}")
        return

    console.print("[yellow]Updating aiops CLI...[/yellow]")

    # Handle development installations differently
    if is_dev_install and cli_path:
        console.print("[dim]Updating development installation...[/dim]")

        # Find the git repository root (should be parent of cli/)
        repo_path = cli_path.parent

        # Check if it's a git repository
        if (repo_path / ".git").exists():
            console.print(f"[dim]Repository path: {repo_path}[/dim]")

            # Pull latest changes
            console.print("[dim]Pulling latest changes from git...[/dim]")
            try:
                result = subprocess.run(
                    ["git", "-C", str(repo_path), "pull"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    error_console.print(f"[red]Git pull failed:[/red] {result.stderr}")
                    error_console.print("[yellow]Continuing with reinstall anyway...[/yellow]")
                else:
                    console.print("[green]✓[/green] Git pull successful")
            except Exception as e:
                error_console.print(f"[yellow]Git pull failed:[/yellow] {e}")
                error_console.print("[yellow]Continuing with reinstall anyway...[/yellow]")

            # Reinstall the CLI package
            console.print("[dim]Reinstalling aiops CLI...[/dim]")

            # Detect if uv is available
            use_uv = False
            try:
                result = subprocess.run(["which", "uv"], capture_output=True, check=False)
                use_uv = (result.returncode == 0)
            except FileNotFoundError:
                pass

            if use_uv:
                reinstall_cmd = ["uv", "pip", "install", "-e", str(cli_path)]
            else:
                reinstall_cmd = [sys.executable, "-m", "pip", "install", "-e", str(cli_path)]

            try:
                result = subprocess.run(reinstall_cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    console.print("[green]✓[/green] aiops CLI reinstalled successfully!")
                    try:
                        new_version = version("aiops-cli")
                        console.print(f"[green]Version: {new_version}[/green]")
                    except PackageNotFoundError:
                        pass
                else:
                    error_console.print(f"[red]Reinstall failed:[/red] {result.stderr}")
                    sys.exit(1)
            except Exception as e:
                error_console.print(f"[red]Reinstall failed:[/red] {e}")
                sys.exit(1)
        else:
            error_console.print("[red]Error:[/red] Not a git repository")
            error_console.print(f"[yellow]Manual update required at:[/yellow] {cli_path}")
            sys.exit(1)
        return

    # For production installations from PyPI
    update_cmd = None
    try:
        result = subprocess.run(["which", "uv"], capture_output=True, check=False)
        if result.returncode == 0:
            update_cmd = ["uv", "pip", "install", "--upgrade", "aiops-cli"]
            console.print("[dim]Using uv for update...[/dim]")
    except FileNotFoundError:
        pass

    if not update_cmd:
        # Fall back to pip
        update_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "aiops-cli"]
        console.print("[dim]Using pip for update...[/dim]")

    try:
        result = subprocess.run(update_cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            console.print("[green]✓[/green] aiops CLI updated successfully!")
            # Try to get new version
            try:
                new_version = version("aiops-cli")
                if new_version != current_version:
                    console.print(f"[green]Updated from {current_version} to {new_version}[/green]")
                else:
                    console.print("[green]Already running the latest version[/green]")
            except PackageNotFoundError:
                pass
        else:
            error_console.print(f"[red]Update failed:[/red] {result.stderr}")
            error_console.print("\n[yellow]If this is a development installation, the update command")
            error_console.print("cannot install from PyPI. Please use git pull and reinstall manually:[/yellow]")
            error_console.print("  cd /path/to/aiops && git pull && uv pip install -e cli")
            sys.exit(1)
    except Exception as e:
        error_console.print(f"[red]Update failed:[/red] {e}")
        sys.exit(1)


# ============================================================================
# SYSTEM COMMANDS
# ============================================================================


@cli.group()
def system() -> None:
    """System management commands (requires admin access)."""


@system.command(name="update")
@click.option("--skip-migrations", is_flag=True, help="Skip database migrations")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def system_update(ctx: click.Context, skip_migrations: bool, output: Optional[str]) -> None:
    """Update aiops application (git pull, install dependencies, run migrations).

    This command:
    1. Pulls the latest code from git
    2. Installs/updates dependencies using uv sync
    3. Runs database migrations (unless --skip-migrations is set)

    Requires admin API key.

    Example:
        aiops system update
        aiops system update --skip-migrations
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        console.print("[yellow]Updating aiops application...[/yellow]")
        result = client.system_update(skip_migrations=skip_migrations)

        console.print(f"[green]✓[/green] {result.get('message', 'Update completed')}")

        # Show detailed results
        results = result.get("results", {})

        if output_format == "table":
            console.print("\n[bold]Update Details:[/bold]")

            # Git pull results
            git_result = results.get("git_pull", {})
            if git_result.get("success"):
                console.print("[green]✓[/green] Git pull: Success")
                if git_result.get("stdout"):
                    console.print(f"  [dim]{git_result['stdout'].strip()}[/dim]")
            else:
                console.print(f"[red]✗[/red] Git pull: Failed - {git_result.get('error', 'Unknown error')}")

            # UV sync results
            uv_result = results.get("uv_sync", {})
            if uv_result.get("success"):
                console.print("[green]✓[/green] Dependencies: Updated")
            else:
                console.print(f"[red]✗[/red] Dependencies: Failed - {uv_result.get('error', 'Unknown error')}")

            # Migration results
            migrate_result = results.get("migrations", {})
            if migrate_result.get("skipped"):
                console.print("[yellow]⊘[/yellow] Migrations: Skipped")
            elif migrate_result.get("success"):
                console.print("[green]✓[/green] Migrations: Completed")
            elif migrate_result:
                console.print(f"[red]✗[/red] Migrations: Failed - {migrate_result.get('error', 'Unknown error')}")

        else:
            # JSON or YAML output
            format_output(result, output_format, console)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@system.command(name="restart")
@click.confirmation_option(prompt="Are you sure you want to restart the aiops application?")
@click.pass_context
def system_restart(ctx: click.Context) -> None:
    """Restart the aiops application.

    This will restart the Flask application service. You will be disconnected briefly.

    Requires admin API key.

    Example:
        aiops system restart
    """
    client = get_client(ctx)

    try:
        console.print("[yellow]Restarting aiops application...[/yellow]")
        result = client.system_restart()

        console.print(f"[green]✓[/green] {result.get('message', 'Restart initiated')}")
        console.print("[dim]The application will restart in a few seconds...[/dim]")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@system.command(name="update-and-restart")
@click.option("--skip-migrations", is_flag=True, help="Skip database migrations")
@click.confirmation_option(prompt="Are you sure you want to update and restart the aiops application?")
@click.pass_context
def system_update_and_restart(ctx: click.Context, skip_migrations: bool) -> None:
    """Update and restart the aiops application.

    This command combines update and restart:
    1. Pulls the latest code from git
    2. Installs/updates dependencies
    3. Runs database migrations (unless --skip-migrations is set)
    4. Restarts the application

    Requires admin API key.

    Example:
        aiops system update-and-restart
    """
    client = get_client(ctx)

    try:
        console.print("[yellow]Updating and restarting aiops application...[/yellow]")
        result = client.system_update_and_restart(skip_migrations=skip_migrations)

        console.print(f"[green]✓[/green] {result.get('message', 'Update completed, restart initiated')}")

        # Show update details
        results = result.get("results", {})
        if results:
            console.print("\n[bold]Update Details:[/bold]")

            git_result = results.get("git_pull", {})
            if git_result.get("success"):
                console.print("[green]✓[/green] Git pull: Success")

            uv_result = results.get("uv_sync", {})
            if uv_result.get("success"):
                console.print("[green]✓[/green] Dependencies: Updated")

            migrate_result = results.get("migrations", {})
            if migrate_result.get("skipped"):
                console.print("[yellow]⊘[/yellow] Migrations: Skipped")
            elif migrate_result.get("success"):
                console.print("[green]✓[/green] Migrations: Completed")

        console.print("\n[dim]The application will restart in a few seconds...[/dim]")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
