"""Main CLI entry point for AIops CLI."""

import subprocess
import sys
import time
from typing import Any, Optional
from urllib.parse import urlparse

import click
from rich.console import Console
from rich.table import Table

from .client import APIClient, APIError
from .config import Config
from .output import format_output

console = Console()
error_console = Console(stderr=True)

AI_TOOL_LABELS = {
    "codex": "Codex CLI",
    "gemini": "@google/gemini-cli",
    "claude": "Claude CLI",
}


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


def attach_to_tmux_session(
    ctx: click.Context,
    *,
    session_id: Optional[str],
    tmux_target: Optional[str],
    ssh_user: Optional[str],
) -> None:
    """Attach to a tmux session owned by the aiops service."""
    attach_target = tmux_target or session_id
    if not attach_target:
        error_console.print(
            "[red]Error:[/red] Missing tmux session identifier to attach.",
        )
        sys.exit(1)

    config: Config = ctx.obj["config"]
    api_url = config.url
    parsed_url = urlparse(api_url)
    ssh_host = parsed_url.hostname

    if not ssh_host:
        error_console.print(
            "[red]Error:[/red] Could not derive SSH host from API URL",
        )
        error_console.print(
            f"[yellow]You can manually attach with:[/yellow] ssh HOST -t tmux attach -t {attach_target}",
        )
        sys.exit(1)

    ssh_target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host

    try:
        subprocess.run(
            ["ssh", "-t", ssh_target, "tmux", "attach-session", "-t", attach_target],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        error_console.print(f"[red]Error attaching to tmux:[/red] {exc}")
        error_console.print(
            f"[yellow]You can manually attach with:[/yellow] ssh {ssh_target} -t tmux attach -t {attach_target}",
        )
        sys.exit(1)
    except FileNotFoundError:
        error_console.print("[red]Error:[/red] ssh not found. Please install OpenSSH to attach.")
        error_console.print(
            f"[yellow]Session is running. You can attach manually with:[/yellow] tmux attach -t {attach_target}",
        )
        sys.exit(1)


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


@issues.command(name="create-assisted")
@click.option("--project", required=True, help="Project ID or name")
@click.option("--integration", type=int, help="Integration ID (if not provided, uses first integration for project)")
@click.option("--description", help="Natural language description of what to work on")
@click.option("--tool", type=click.Choice(["claude", "codex", "gemini"]), default="claude", help="AI tool to use")
@click.option("--type", "issue_type", type=click.Choice(["feature", "bug"]), help="Issue type hint")
@click.option("--create-branch", is_flag=True, help="Create feature/fix branch")
@click.option("--start-session", is_flag=True, help="Start AI session for the issue")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def issues_create_assisted(
    ctx: click.Context,
    project: str,
    integration: Optional[int],
    description: Optional[str],
    tool: str,
    issue_type: Optional[str],
    create_branch: bool,
    start_session: bool,
    output: Optional[str],
) -> None:
    """Create issue with AI assistance from natural language description.

    This command uses AI to generate a well-formatted issue from your description.
    It can optionally create a feature branch and start an AI session.

    Examples:

        # Interactive mode (prompts for description)
        aiops issues create-assisted --project myproject

        # Direct mode
        aiops issues create-assisted --project myproject \\
            --description "Add user authentication with OAuth2" \\
            --tool claude --type feature

        # Create branch and start session
        aiops issues create-assisted --project myproject \\
            --description "Fix login validation bug" \\
            --type bug --create-branch --start-session
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        # Resolve project ID
        project_id = resolve_project_id(client, project)

        # Get integration ID if not provided
        if not integration:
            # Get first integration for project
            integrations = client.get("/api/v1/issues/integrations", params={"project_id": project_id})
            if not integrations:
                error_console.print(f"[red]Error:[/red] No integrations found for project {project}")
                sys.exit(1)
            integration = integrations[0]["id"]
            console.print(f"Using integration: {integrations[0]['name']} (ID: {integration})")

        # Get description if not provided
        if not description:
            console.print("[yellow]Enter your description of what you want to work on:[/yellow]")
            console.print("[dim](Type your description, press Enter twice when done)[/dim]")
            lines = []
            empty_count = 0
            while True:
                try:
                    line = input()
                    if not line:
                        empty_count += 1
                        if empty_count >= 2:
                            break
                    else:
                        empty_count = 0
                        lines.append(line)
                except EOFError:
                    break
            description = "\n".join(lines).strip()

            if not description:
                error_console.print("[red]Error:[/red] Description cannot be empty")
                sys.exit(1)

        # Show what we're doing
        console.print(f"\n[cyan]Creating issue with AI assistance...[/cyan]")
        console.print(f"  Tool: {tool}")
        console.print(f"  Project ID: {project_id}")
        console.print(f"  Integration ID: {integration}")
        if issue_type:
            console.print(f"  Type: {issue_type}")
        if create_branch:
            console.print(f"  Create branch: Yes")
        if start_session:
            console.print(f"  Start session: Yes")

        # Create AI-assisted issue
        payload = {
            "project_id": project_id,
            "integration_id": integration,
            "description": description,
            "ai_tool": tool,
            "create_branch": create_branch,
            "start_session": start_session,
        }
        if issue_type:
            payload["issue_type"] = issue_type

        console.print("\n[cyan]Generating issue with AI...[/cyan]")
        result = client.post("/api/v1/issues/create-assisted", payload)

        console.print("[green]✓ Issue created successfully![/green]\n")

        # Display results
        if output_format == "json":
            import json
            console.print(json.dumps(result, indent=2))
        elif output_format == "yaml":
            import yaml
            console.print(yaml.dump(result, default_flow_style=False))
        else:
            # Table format
            console.print(f"[bold]Issue #{result['external_id']}[/bold]: {result['title']}")
            console.print(f"URL: {result['issue_url']}")
            console.print(f"Database ID: {result['issue_id']}")
            if result.get("labels"):
                console.print(f"Labels: {', '.join(result['labels'])}")
            if result.get("branch_name"):
                console.print(f"\n[green]✓ Branch created:[/green] {result['branch_name']}")
            if result.get("branch_error"):
                console.print(f"\n[yellow]⚠ Branch creation failed:[/yellow] {result['branch_error']}")
            if result.get("session_url"):
                console.print(f"\n[green]✓ Session created[/green]")
                console.print(f"Session URL: {result['session_url']}")
            if result.get("session_error"):
                console.print(f"\n[yellow]⚠ Session creation failed:[/yellow] {result['session_error']}")

            console.print(f"\n[dim]Next steps:[/dim]")
            console.print(f"  1. Review the issue at {result['issue_url']}")
            if result.get("branch_name"):
                console.print(f"  2. Checkout branch: git checkout {result['branch_name']}")
            if result.get("session_url"):
                console.print(f"  3. Start working in the AI session")
            else:
                console.print(f"  2. Start working: aiops issues work {result['issue_id']}")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except Exception as exc:
        error_console.print(f"[red]Unexpected error:[/red] {exc}")
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
@click.argument("body", required=False)
@click.option("--file", "-f", "file_path", type=click.Path(exists=True, dir_okay=False), help="Read comment content from file")
@click.option("--no-mention-resolve", is_flag=True, help="Disable automatic @mention resolution")
@click.pass_context
def issues_comment(
    ctx: click.Context,
    issue_id: int,
    body: Optional[str],
    file_path: Optional[str],
    no_mention_resolve: bool,
) -> None:
    """Add comment to issue.

    Automatically resolves @mentions to Jira account IDs by looking up users
    from the issue's comment history.

    Examples:
        aiops issues comment 254 "Quick update"
        aiops issues comment 254 "@reviewer Thanks for the info!"
        aiops issues comment 254 --file /tmp/error.log
        aiops issues comment 254 -f analysis.md
        aiops issues comment 254 "Fixed the issue" --no-mention-resolve
    """
    client = get_client(ctx)

    try:
        # Get comment body from either argument or file
        if file_path and body:
            error_console.print("[red]Error:[/red] Cannot specify both BODY and --file option")
            sys.exit(1)
        elif file_path:
            # Read from file
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    body = f.read()
                if not body.strip():
                    error_console.print(f"[red]Error:[/red] File '{file_path}' is empty")
                    sys.exit(1)
            except (IOError, OSError) as exc:
                error_console.print(f"[red]Error:[/red] Failed to read file '{file_path}': {exc}")
                sys.exit(1)
        elif not body:
            error_console.print("[red]Error:[/red] Must provide either BODY argument or --file option")
            sys.exit(1)

        # Resolve @mentions unless disabled
        if not no_mention_resolve and "@" in body:
            # Fetch issue to get comments for user resolution
            issue = client.get_issue(issue_id)
            comments = issue.get("comments", [])

            if comments:
                from .mentions import extract_jira_users_from_comments, resolve_mentions

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
        aiops issues modify-comment 254 12345 "@reviewer Updated the details!"
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
                from .mentions import extract_jira_users_from_comments, resolve_mentions

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
        aiops issues sync --tenant example        # Sync issues for a tenant
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
        failed_projects = result.get("failed_projects", [])
        message = result.get("message", "")
        success_count = result.get("success_count", 0)
        failure_count = result.get("failure_count", 0)

        # Show summary message with appropriate styling
        if failure_count > 0:
            if success_count > 0:
                console.print(f"[yellow]⚠[/yellow] {message}")
            else:
                console.print(f"[red]✗[/red] {message}")
        else:
            console.print(f"[green]✓[/green] {message}")

        if synced > 0:
            console.print(f"[green]Total issues synchronized:[/green] {synced}")

        if projects and output_format == "table":
            # Display successful project sync details in table format
            console.print()
            table = Table(title="Successful Syncs")
            table.add_column("Provider", style="cyan", no_wrap=True)
            table.add_column("Tenant", style="yellow")
            table.add_column("Project", style="magenta")
            table.add_column("Integration", style="blue")
            table.add_column("Issues", style="green", justify="right")

            for proj in projects:
                table.add_row(
                    proj.get("provider", ""),
                    proj.get("tenant_name", ""),
                    proj.get("project_name", ""),
                    proj.get("integration_name", ""),
                    str(proj.get("issues_synced", 0)),
                )

            console.print(table)
        elif projects:
            # Use standard format_output for JSON/YAML
            format_output(projects, output_format, console, title="Successful Syncs")

        # Display failed integrations if any
        if failed_projects:
            if output_format == "table":
                console.print()
                failed_table = Table(title="Failed Syncs", title_style="red")
                failed_table.add_column("Provider", style="cyan", no_wrap=True)
                failed_table.add_column("Tenant", style="yellow")
                failed_table.add_column("Project", style="magenta")
                failed_table.add_column("Integration", style="blue")
                failed_table.add_column("Status", style="red")

                for proj in failed_projects:
                    failed_table.add_row(
                        proj.get("provider", ""),
                        proj.get("tenant_name", ""),
                        proj.get("project_name", ""),
                        proj.get("integration_name", ""),
                        "Failed",
                    )

                console.print(failed_table)
                console.print(
                    "[dim]Check application logs for detailed error messages[/dim]"
                )
            else:
                # Use standard format_output for JSON/YAML
                format_output(failed_projects, output_format, console, title="Failed Syncs")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="sessions")
@click.option("--project", help="Filter by project ID or name")
@click.option(
    "--attach",
    "attach_session",
    help="Attach to a session by ID/prefix or tmux target (see output table)",
)
@click.option(
    "--all-users",
    is_flag=True,
    help="Show sessions for all users (admin only, implicit for admins)",
)
@click.pass_context
def issues_sessions(
    ctx: click.Context,
    project: Optional[str],
    attach_session: Optional[str],
    all_users: bool,
) -> None:
    """List active AI sessions."""
    client = get_client(ctx)

    try:
        all_sessions = []

        # Auto-enable all-users for admins
        if not all_users and client.is_admin():
            all_users = True

        # When attaching, always fetch all users' sessions so we can find the target
        # (admins should be able to attach to any session)
        fetch_all_users = all_users or bool(attach_session)

        if project:
            # Single project - resolve name to ID if needed
            project_id = resolve_project_id(client, project)
            sessions = client.list_ai_sessions(project_id, all_users=fetch_all_users)
            # Add project info to each session
            for session in sessions:
                session["project_id"] = project_id
            all_sessions.extend(sessions)
        else:
            # No project specified - fetch sessions from all projects
            projects = client.list_projects()
            for idx, proj in enumerate(projects):
                # Add small delay between requests to avoid rate limiting
                if idx > 0:
                    time.sleep(0.1)
                proj_id = proj["id"]
                sessions = client.list_ai_sessions(proj_id, all_users=fetch_all_users)
                # Add project info to each session
                for session in sessions:
                    session["project_id"] = proj_id
                    session["project_name"] = proj["name"]
                all_sessions.extend(sessions)

        if not all_sessions:
            console.print("[yellow]No active AI sessions found[/yellow]")
            if attach_session:
                error_console.print(
                    "[red]Error:[/red] Unable to attach because no sessions are running.",
                )
                sys.exit(1)
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

        # If attaching, resolve the requested session
        if attach_session:
            identifier = attach_session.strip()
            if identifier.endswith("..."):
                identifier = identifier[:-3]
            target_session = None
            for session in all_sessions:
                sid = str(session.get("session_id", ""))
                tmux_target = session.get("tmux_target", "")
                if identifier and (sid == identifier or sid.startswith(identifier)):
                    target_session = session
                    break
                if identifier and tmux_target == identifier:
                    target_session = session
                    break

            if not target_session:
                error_console.print(
                    f"[red]Error:[/red] Session '{attach_session}' not found in the list above.",
                )
                sys.exit(1)

            console.print("\n[yellow]Attaching to tmux session...[/yellow]")
            console.print("[dim]Press Ctrl+B then D to detach from tmux[/dim]\n")

            # Track the attach activity in the database
            session_db_id = target_session.get("id")
            if session_db_id:
                try:
                    client.post(f"/ai/sessions/{session_db_id}/attach")
                except APIError:
                    # Don't fail attach if tracking fails - just log and continue
                    pass

            attach_to_tmux_session(
                ctx,
                session_id=str(target_session.get("session_id")),
                tmux_target=target_session.get("tmux_target"),
                ssh_user=target_session.get("ssh_user"),
            )

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@issues.command(name="start")
@click.option("--project", help="Project ID or name (required if multiple projects)")
@click.option("--issue", type=int, help="Issue ID to work on")
@click.option("--tool", type=click.Choice(["claude", "codex", "gemini", "shell"]), help="AI tool to use")
@click.option("--prompt", help="Initial prompt to send to the AI")
@click.option("--user", help="User email or ID to start session as (admin only)")
@click.option("--attach", is_flag=True, default=True, help="Attach to session after starting (default: true)")
@click.option("--yolo", is_flag=True, help="Skip all permissions for Claude (dangerous)")
@click.pass_context
def issues_start(
    ctx: click.Context,
    project: Optional[str],
    issue: Optional[int],
    tool: Optional[str],
    prompt: Optional[str],
    user: Optional[str],
    attach: bool,
    yolo: bool,
) -> None:
    """Start a new AI session on a project.

    Examples:
        aiops issues start --project aiops --tool shell
        aiops issues start --project 6 --issue 123 --tool claude
        aiops issues start --project aiops --tool codex --prompt "Review code"
        aiops issues start --project aiops --tool shell --user michael@floads.io
    """
    client = get_client(ctx)

    try:
        if not project:
            error_console.print("[red]Error:[/red] --project is required")
            sys.exit(1)

        # Resolve project
        project_id = resolve_project_id(client, project)

        # Resolve user if specified
        user_id = None
        if user:
            # Try to find user by email or ID
            users_response = client.get("users")
            users = users_response.get("users", [])

            # Try as ID first
            try:
                target_user_id = int(user)
                user_obj = next((u for u in users if u["id"] == target_user_id), None)
            except ValueError:
                # Try as email
                user_obj = next((u for u in users if u.get("email") == user), None)

            if not user_obj:
                error_console.print(f"[red]Error:[/red] User '{user}' not found")
                sys.exit(1)

            user_id = user_obj["id"]
            console.print(f"[blue]Starting session as:[/blue] {user_obj.get('email', user_obj['id'])}")

        # Start AI session
        payload: dict[str, Any] = {}
        if issue:
            payload["issue_id"] = issue
        if tool:
            payload["tool"] = tool
        if prompt:
            payload["prompt"] = prompt
        if user_id:
            payload["user_id"] = user_id
        if yolo:
            payload["permission_mode"] = "yolo"

        url = f"{client.base_url}/api/v1/projects/{project_id}/ai/sessions"
        response = client.session.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

        session_id = result.get("session_id")
        workspace_path = result.get("workspace_path")
        ssh_user = result.get("ssh_user")
        tmux_target = result.get("tmux_target")
        is_existing = result.get("existing", False)

        if is_existing:
            console.print(f"[green]✓[/green] Reusing existing session (session ID: {session_id})")
        else:
            console.print(f"[green]✓[/green] AI session started (session ID: {session_id})")

        if workspace_path:
            console.print(f"[blue]Workspace:[/blue] {workspace_path}")
        if tmux_target:
            console.print(f"[blue]Tmux target:[/blue] {tmux_target}")

        # Attach if requested
        if attach and tmux_target:
            console.print("\n[yellow]Attaching to tmux session...[/yellow]")
            console.print("[dim]Press Ctrl+B then D to detach from tmux[/dim]\n")
            attach_to_tmux_session(
                ctx,
                session_id=session_id,
                tmux_target=tmux_target,
                ssh_user=ssh_user,
            )
        elif tmux_target:
            console.print(
                f"\n[yellow]To attach:[/yellow] aiops issues sessions --attach {tmux_target}"
            )

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except Exception as exc:
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
        context_sources = result.get("context_sources", [])  # Sources that were merged
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
        if context_populated and context_sources:
            sources_str = " + ".join(context_sources)
            console.print(f"[blue]Context:[/blue] AGENTS.override.md populated from: {sources_str}")
        elif context_populated:
            console.print("[blue]Context:[/blue] AGENTS.override.md populated with issue details")

        # If attach flag is set, attach to tmux session
        if attach:
            console.print("\n[yellow]Attaching to tmux session...[/yellow]")
            console.print("[dim]Press Ctrl+B then D to detach from tmux[/dim]\n")
            attach_to_tmux_session(
                ctx,
                session_id=session_id,
                tmux_target=tmux_target,
                ssh_user=ssh_user,
            )
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


@git.command(name="pr-create")
@click.argument("project")
@click.option("--title", "-t", required=True, help="Pull request title")
@click.option("--description", "-d", help="Pull request description")
@click.option("--source", "-s", required=True, help="Source branch")
@click.option("--target", "-b", default="main", help="Target branch (default: main)")
@click.option("--assignee", "-a", help="GitHub username to assign as reviewer")
@click.option("--draft", is_flag=True, help="Create as draft PR")
@click.pass_context
def git_pr_create(
    ctx: click.Context,
    project: str,
    title: str,
    description: Optional[str],
    source: str,
    target: str,
    assignee: Optional[str],
    draft: bool,
) -> None:
    """Create a pull request (GitHub) or merge request (GitLab)."""
    client = get_client(ctx)

    try:
        project_id = resolve_project_id(client, project)
        result = client.git_create_pr(
            project_id=project_id,
            title=title,
            description=description or "",
            source_branch=source,
            target_branch=target,
            assignee=assignee,
            draft=draft,
        )
        console.print(f"[green]✓[/green] Pull/Merge request created: {result['url']}")
        console.print(f"  Number: {result['number']}")
        console.print(f"  Title: {result['title']}")
        if assignee:
            console.print(f"  Assigned to: {assignee}")
    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@git.command(name="pr-merge")
@click.argument("project")
@click.argument("pr_number", type=int)
@click.option(
    "--method",
    "-m",
    type=click.Choice(["merge", "squash", "rebase"], case_sensitive=False),
    default="merge",
    help="Merge method (default: merge)",
)
@click.option(
    "--delete-branch",
    is_flag=True,
    help="Delete source branch after merge",
)
@click.option(
    "--message",
    help="Custom merge commit message",
)
@click.pass_context
def git_pr_merge(
    ctx: click.Context,
    project: str,
    pr_number: int,
    method: str,
    delete_branch: bool,
    message: Optional[str],
) -> None:
    """Merge a pull request (GitHub) or merge request (GitLab)."""
    client = get_client(ctx)

    try:
        project_id = resolve_project_id(client, project)
        result = client.git_merge_pr(
            project_id=project_id,
            pr_number=pr_number,
            method=method.lower(),
            delete_branch=delete_branch,
            commit_message=message,
        )

        console.print(f"[green]✓[/green] Pull/Merge request #{pr_number} merged successfully")
        console.print(f"  Title: {result['title']}")
        console.print(f"  URL: {result['url']}")
        console.print(f"  Method: {method}")
        if result.get("sha"):
            console.print(f"  Merge SHA: {result['sha']}")
        if delete_branch:
            console.print("  Source branch deleted")
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
# SESSIONS COMMANDS
# ============================================================================


@cli.group()
def sessions() -> None:
    """Session management commands (not tied to specific issues)."""


@sessions.command(name="start")
@click.option("--project", required=True, help="Project ID or name")
@click.option("--tool", type=click.Choice(["claude", "codex", "gemini", "shell"]), help="AI tool to use")
@click.option("--prompt", help="Initial prompt to send")
@click.option("--user", help="User email or ID to start session as (admin only)")
@click.option("--attach/--no-attach", default=True, help="Attach to session after starting")
@click.option("--yolo", is_flag=True, help="Skip all permissions for Claude (dangerous)")
@click.pass_context
def sessions_start(
    ctx: click.Context,
    project: str,
    tool: Optional[str],
    prompt: Optional[str],
    user: Optional[str],
    attach: bool,
    yolo: bool,
) -> None:
    """Start a generic session (not tied to a specific issue).

    Examples:
        aiops sessions start --project aiops --tool shell
        aiops sessions start --project 6 --tool codex --prompt "Review code"
        aiops sessions start --project aiops --tool shell --user user@example.com
    """
    client = get_client(ctx)

    try:
        # Resolve project
        project_id = resolve_project_id(client, project)

        # Resolve user if specified
        user_id = None
        if user:
            users_response = client.get("users")
            users = users_response.get("users", [])

            try:
                target_user_id = int(user)
                user_obj = next((u for u in users if u["id"] == target_user_id), None)
            except ValueError:
                user_obj = next((u for u in users if u.get("email") == user), None)

            if not user_obj:
                error_console.print(f"[red]Error:[/red] User '{user}' not found")
                sys.exit(1)

            user_id = user_obj["id"]
            console.print(f"[blue]Starting session as:[/blue] {user_obj.get('email', user_obj['id'])}")

        # Start session
        payload: dict[str, Any] = {}
        if tool:
            payload["tool"] = tool
        if prompt:
            payload["prompt"] = prompt
        if user_id:
            payload["user_id"] = user_id
        if yolo:
            payload["permission_mode"] = "yolo"

        url = f"{client.base_url}/api/v1/projects/{project_id}/ai/sessions"
        response = client.session.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

        session_id = result.get("session_id")
        workspace_path = result.get("workspace_path")
        ssh_user = result.get("ssh_user")
        tmux_target = result.get("tmux_target")
        is_existing = result.get("existing", False)
        context_populated = result.get("context_populated", False)
        context_sources = result.get("context_sources", [])

        if is_existing:
            console.print(f"[green]✓[/green] Reusing existing session (session ID: {session_id})")
        else:
            console.print(f"[green]✓[/green] Session started (session ID: {session_id})")

        if workspace_path:
            console.print(f"[blue]Workspace:[/blue] {workspace_path}")
        if tmux_target:
            console.print(f"[blue]Tmux target:[/blue] {tmux_target}")
        if context_populated and context_sources:
            sources_str = " + ".join(context_sources)
            console.print(f"[blue]Context:[/blue] AGENTS.override.md populated from: {sources_str}")

        if attach and tmux_target:
            console.print("\n[yellow]Attaching to session...[/yellow]")
            console.print("[dim]Press Ctrl+B then D to detach[/dim]\n")
            attach_to_tmux_session(
                ctx,
                session_id=session_id,
                tmux_target=tmux_target,
                ssh_user=ssh_user,
            )
        elif tmux_target:
            console.print(
                f"\n[yellow]To attach:[/yellow] aiops sessions attach {tmux_target}"
            )

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@sessions.command(name="list")
@click.option("--project", help="Filter by project ID or name")
@click.option("--all-users", is_flag=True, help="Show sessions for all users (admin only, implicit for admins)")
@click.pass_context
def sessions_list(
    ctx: click.Context,
    project: Optional[str],
    all_users: bool,
) -> None:
    """List active sessions."""
    client = get_client(ctx)

    try:
        # Auto-enable all-users for admins
        if not all_users and client.is_admin():
            all_users = True

        # Use the global sessions endpoint to get all sessions (including issue sessions)
        project_id = resolve_project_id(client, project) if project else None
        all_sessions = client.list_all_sessions(
            project_id=project_id,
            all_users=all_users,
            active_only=True,
            limit=200,
        )

        if not all_sessions:
            console.print("[yellow]No active sessions found[/yellow]")
            return

        title = f"Active Sessions (Project {project})" if project else "Active Sessions (All Projects)"
        table = Table(title=title)
        table.add_column("Session ID", style="cyan", no_wrap=True, width=15)
        table.add_column("Issue", style="magenta", no_wrap=True, width=8)
        table.add_column("Tool", style="green", no_wrap=True, width=10)
        table.add_column("Status", style="white", no_wrap=True, width=8)
        if not project:
            table.add_column("Project", style="yellow", no_wrap=True, width=12)
        table.add_column("Tmux Target", style="blue", overflow="fold")

        for session in all_sessions:
            session_id = session.get("session_id", "")[:12] + "..."
            issue_id = str(session.get("issue_id") or "-")
            tool_name = session.get("tool", "unknown")
            tmux_target = session.get("tmux_target", "")
            pane_dead = session.get("pane_dead", False)
            status = "[red]dead[/red]" if pane_dead else "[green]alive[/green]"

            if project:
                table.add_row(session_id, issue_id, tool_name, status, tmux_target)
            else:
                project_name = session.get("project_name", str(session.get("project_id", "-")))
                table.add_row(session_id, issue_id, tool_name, status, project_name, tmux_target)

        console.print(table)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@sessions.command(name="attach")
@click.argument("target")
@click.option("--project", help="Filter by project ID or name")
@click.pass_context
def sessions_attach(
    ctx: click.Context,
    target: str,
    project: Optional[str],
) -> None:
    """Attach to a session by ID/prefix or tmux target.

    Examples:
        aiops sessions attach cb3877c65dbd
        aiops sessions attach user:aiops-p6
    """
    client = get_client(ctx)

    try:
        # Use the global sessions endpoint to get all sessions from database
        # Auto-enable all-users for admins
        all_users = client.is_admin()
        project_id = resolve_project_id(client, project) if project else None

        all_sessions = client.list_all_sessions(
            project_id=project_id,
            all_users=all_users,
            active_only=True,
            limit=200,
        )

        if not all_sessions:
            error_console.print("[red]Error:[/red] No active sessions found")
            sys.exit(1)

        # Find matching session
        identifier = target.strip()
        if identifier.endswith("..."):
            identifier = identifier[:-3]

        target_session = None
        for session in all_sessions:
            sid = str(session.get("session_id", ""))
            tmux_target = session.get("tmux_target", "")
            if identifier and (sid == identifier or sid.startswith(identifier)):
                target_session = session
                break
            if identifier and tmux_target == identifier:
                target_session = session
                break

        if not target_session:
            error_console.print(
                f"[red]Error:[/red] Session '{target}' not found"
            )
            sys.exit(1)

        # Validate that the session's tmux target still exists
        session_db_id = target_session.get("id")
        if session_db_id:
            validation = client.validate_session(session_db_id)
            if not validation.get("exists"):
                if validation.get("marked_inactive"):
                    error_console.print(
                        f"[red]Error:[/red] Session '{target}' no longer exists (tmux session terminated)"
                    )
                    error_console.print("[yellow]The session has been marked as inactive in the database.[/yellow]")
                else:
                    error_console.print(
                        f"[red]Error:[/red] Cannot attach to session '{target}' - no tmux target available"
                    )
                sys.exit(1)

        console.print("\n[yellow]Attaching to session...[/yellow]")
        console.print("[dim]Press Ctrl+B then D to detach[/dim]\n")

        # Track the attach activity in the database
        try:
            client.post(f"/ai/sessions/{session_db_id}/attach")
        except APIError:
            # Don't fail attach if tracking fails - just log and continue
            pass

        # Use tmux_server_user (Flask process user) for SSH, not linux_username (process owner inside tmux)
        ssh_user = target_session.get("tmux_server_user") or target_session.get("ssh_user")

        attach_to_tmux_session(
            ctx,
            session_id=str(target_session.get("session_id")),
            tmux_target=target_session.get("tmux_target"),
            ssh_user=ssh_user,
        )

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@sessions.command(name="respawn")
@click.argument("target")
@click.option("--project", help="Filter by project ID or name")
@click.pass_context
def sessions_respawn(
    ctx: click.Context,
    target: str,
    project: Optional[str],
) -> None:
    """Respawn a dead pane for a session.

    Restarts the pane with its original command. Only works for dead panes.

    Examples:
        aiops sessions respawn cb3877c65dbd
        aiops sessions respawn user:aiops-p6
    """
    client = get_client(ctx)

    try:
        # Use the global sessions endpoint to get all sessions from database
        # Auto-enable all-users for admins
        all_users = client.is_admin()
        project_id = resolve_project_id(client, project) if project else None

        all_sessions = client.list_all_sessions(
            project_id=project_id,
            all_users=all_users,
            active_only=True,
            limit=200,
        )

        if not all_sessions:
            error_console.print("[red]Error:[/red] No active sessions found")
            sys.exit(1)

        # Find matching session
        identifier = target.strip()
        if identifier.endswith("..."):
            identifier = identifier[:-3]

        target_session = None
        for session in all_sessions:
            sid = str(session.get("session_id", ""))
            tmux_target = session.get("tmux_target", "")
            if identifier and (sid == identifier or sid.startswith(identifier)):
                target_session = session
                break
            if identifier and tmux_target == identifier:
                target_session = session
                break

        if not target_session:
            error_console.print(
                f"[red]Error:[/red] Session '{target}' not found"
            )
            sys.exit(1)

        # Check if pane is dead
        pane_dead = target_session.get("pane_dead", False)
        if not pane_dead:
            error_console.print(
                f"[yellow]Warning:[/yellow] Session '{target}' is still alive, no need to respawn"
            )
            sys.exit(0)

        # Call respawn API
        session_project_id = target_session.get("project_id")
        tmux_target_str = target_session.get("tmux_target")

        if not session_project_id or not tmux_target_str:
            error_console.print("[red]Error:[/red] Session missing project or tmux target")
            sys.exit(1)

        url = f"projects/{session_project_id}/tmux/respawn"
        payload = {"tmux_target": tmux_target_str}

        client.post(url, json=payload)
        console.print(f"[green]✓[/green] Successfully respawned pane: {tmux_target_str}")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@sessions.command(name="kill")
@click.argument("target")
@click.option("--project", help="Filter by project ID or name")
@click.pass_context
def sessions_kill(
    ctx: click.Context,
    target: str,
    project: Optional[str],
) -> None:
    """Kill/close a tmux session.

    This will terminate the tmux window and end the AI session.

    Examples:
        aiops sessions kill cb3877c65dbd
        aiops sessions kill ivo:aiops-p6
        aiops sessions kill b40b6749d78f --project flamelet-kbe
    """
    client = get_client(ctx)

    try:
        # Use the global sessions endpoint to get all sessions from database
        # Auto-enable all-users for admins
        all_users = client.is_admin()
        project_id = resolve_project_id(client, project) if project else None

        all_sessions = client.list_all_sessions(
            project_id=project_id,
            all_users=all_users,
            active_only=True,
            limit=200,
        )

        if not all_sessions:
            error_console.print("[red]Error:[/red] No active sessions found")
            sys.exit(1)

        # Find matching session
        identifier = target.strip()
        if identifier.endswith("..."):
            identifier = identifier[:-3]

        target_session = None
        for session in all_sessions:
            sid = str(session.get("session_id", ""))
            tmux_target = session.get("tmux_target", "")
            if identifier and (sid == identifier or sid.startswith(identifier)):
                target_session = session
                break
            if identifier and tmux_target == identifier:
                target_session = session
                break

        if not target_session:
            error_console.print(
                f"[red]Error:[/red] Session '{target}' not found"
            )
            sys.exit(1)

        # Get session details
        session_project_id = target_session.get("project_id")
        tmux_target_str = target_session.get("tmux_target")
        tool = target_session.get("tool", "")
        issue_id = target_session.get("issue_id")

        if not session_project_id or not tmux_target_str:
            error_console.print("[red]Error:[/red] Session missing project or tmux target")
            sys.exit(1)

        # Display session info
        console.print("\n[yellow]Session to kill:[/yellow]")
        console.print(f"  Tmux target: {tmux_target_str}")
        console.print(f"  Tool: {tool}")
        if issue_id:
            console.print(f"  Issue: #{issue_id}")

        # Call close API
        url = f"projects/{session_project_id}/tmux/close"
        payload = {"tmux_target": tmux_target_str}

        client.post(url, json=payload)
        console.print(f"\n[green]✓[/green] Successfully killed session: {tmux_target_str}")

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
    from importlib.metadata import PackageNotFoundError, version
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
                import json
                import urllib.request
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


@system.command(name="status")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def system_status(ctx: click.Context, output: Optional[str]) -> None:
    """Check system status of aiops core components.

    Displays health status for:
    - Database connectivity
    - Tmux server availability
    - Git installation
    - AI tools (Claude, Codex, Gemini)
    - Workspace directories
    - Issue tracker integrations
    - Active AI sessions

    Requires admin API key.

    Example:
        aiops system status
        aiops system status --output json
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        status = client.get_system_status()

        if output_format == "table":
            # Overall health header
            overall_health = status.get("healthy", False)
            if overall_health:
                console.print("[green]✓ System Status: Healthy[/green]\n")
            else:
                console.print("[red]✗ System Status: Unhealthy[/red]\n")

            # Component status table
            console.print("[bold]Component Status:[/bold]")
            components = status.get("components", {})

            for component_name, component_data in components.items():
                healthy = component_data.get("healthy", False)
                message = component_data.get("message", "No status")

                # Format component name
                display_name = component_name.replace("_", " ").title()

                # Status indicator
                if healthy:
                    console.print(f"[green]✓[/green] {display_name}: {message}")
                else:
                    console.print(f"[red]✗[/red] {display_name}: {message}")

                # Show details if available
                details = component_data.get("details", {})
                if details and isinstance(details, dict):
                    for key, value in details.items():
                        if key == "tools" and isinstance(value, dict):
                            # Special handling for AI tools
                            for tool, tool_info in value.items():
                                available = tool_info.get("available", False)
                                symbol = "✓" if available else "✗"
                                color = "green" if available else "red"
                                console.print(f"  [{color}]{symbol}[/{color}] {tool}")
                        elif key == "integrations" and isinstance(value, dict):
                            # Special handling for integrations
                            for integration, int_info in value.items():
                                enabled = int_info.get("enabled", False)
                                provider = int_info.get("provider", "unknown")
                                symbol = "✓" if enabled else "○"
                                color = "green" if enabled else "dim"
                                console.print(f"  [{color}]{symbol}[/{color}] {integration} ({provider})")
                        elif key == "projects" and isinstance(value, list):
                            # Special handling for SSH connectivity projects
                            for proj in value:
                                ssh_ok = proj.get("ssh_ok", False)
                                project_name = proj.get("project_name", "unknown")
                                hostname = proj.get("hostname", "unknown")
                                error = proj.get("error")
                                ssh_key_info = proj.get("ssh_key", {})

                                symbol = "✓" if ssh_ok else "✗"
                                color = "green" if ssh_ok else "red"

                                # Build key info display
                                key_display = ""
                                if ssh_key_info:
                                    key_name = ssh_key_info.get("name", "unknown")
                                    key_source = ssh_key_info.get("source", "?")
                                    key_storage = ssh_key_info.get("storage", "?")
                                    key_display = f" [dim]({key_name} via {key_source}, {key_storage})[/dim]"

                                if ssh_ok:
                                    console.print(f"  [{color}]{symbol}[/{color}] {project_name}: {hostname}{key_display}")
                                else:
                                    console.print(f"  [{color}]{symbol}[/{color}] {project_name}: {hostname} {error}{key_display}")
                        elif key not in ["error"]:
                            # Show other details
                            console.print(f"  [dim]{key}: {value}[/dim]")

            # Summary
            summary = status.get("summary", {})
            console.print("\n[bold]Summary:[/bold]")
            console.print(f"  Healthy: {summary.get('healthy_components', 0)}/{summary.get('total_components', 0)} components")
            console.print(f"  Timestamp: {status.get('timestamp', 'N/A')}")

        else:
            # JSON or YAML output
            format_output(status, output_format, console)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


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
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def system_restart(ctx: click.Context, yes: bool) -> None:
    """Restart the aiops application.

    This will restart the Flask application service. You will be disconnected briefly.

    Requires admin API key.

    Example:
        aiops system restart
        aiops system restart --yes
    """
    if not yes:
        click.confirm("Are you sure you want to restart the aiops application?", abort=True)

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
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def system_update_and_restart(ctx: click.Context, skip_migrations: bool, yes: bool) -> None:
    """Update and restart the aiops application.

    This command combines update and restart:
    1. Pulls the latest code from git
    2. Installs/updates dependencies
    3. Runs database migrations (unless --skip-migrations is set)
    4. Restarts the application

    Requires admin API key.

    Example:
        aiops system update-and-restart
        aiops system update-and-restart --yes
    """
    if not yes:
        click.confirm("Are you sure you want to update and restart the aiops application?", abort=True)

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


@system.command(name="update-ai-tool")
@click.argument("tool", type=click.Choice(["codex", "gemini", "claude"]))
@click.option("--source", type=click.Choice(["npm", "brew"]), required=True, help="Update source (npm or brew)")
@click.pass_context
def system_update_ai_tool(ctx: click.Context, tool: str, source: str) -> None:
    """Update an AI tool CLI on the server (e.g., codex, gemini).

    Requires admin API key.

    Examples:
        aiops system update-ai-tool codex --source npm
        aiops system update-ai-tool gemini --source brew
    """
    client = get_client(ctx)
    tool_label = AI_TOOL_LABELS.get(tool, tool)

    try:
        console.print(f"[yellow]Updating {tool_label} via {source.upper()}...[/yellow]")
        result = client.update_ai_tool(tool, source)

        if result.get("success"):
            console.print(f"[green]✓[/green] {result.get('message')}")
            if result.get("stdout"):
                console.print("[bold]Output:[/bold]")
                console.print(f"[dim]{result.get('stdout')}[/dim]")
        else:
            error_console.print(f"[red]✗[/red] {result.get('message')}")
            if result.get("stderr"):
                error_console.print("[bold]Error Output:[/bold]")
                error_console.print(f"[dim]{result.get('stderr')}[/dim]")
            sys.exit(1)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@system.command(name="switch-branch")
@click.argument("branch", required=True)
@click.option("--restart/--no-restart", default=True, help="Restart after switching branch")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def system_switch_branch(ctx: click.Context, branch: str, restart: bool, yes: bool) -> None:
    """Switch the aiops backend to a specific git branch.

    This command allows you to test feature branches by:
    1. Switching the production backend (/home/syseng/aiops) to the specified branch
    2. Optionally restarting the service to apply changes

    Requires admin API key.

    Examples:
        # Switch to feature branch and restart
        aiops system switch-branch feature/36-ai-assisted-issue-creation

        # Switch without restarting
        aiops system switch-branch main --no-restart

        # Switch without confirmation prompt
        aiops system switch-branch feature/new-feature -y
    """
    client = get_client(ctx)

    if not yes:
        restart_msg = " and restart" if restart else ""
        if not click.confirm(
            f"Are you sure you want to switch backend to branch '{branch}'{restart_msg}?",
            default=False,
        ):
            console.print("[yellow]Aborted![/yellow]")
            sys.exit(0)

    try:
        console.print(f"[cyan]Switching backend to branch '{branch}'...[/cyan]")

        # Call API to switch branch
        result = client.post("/system/switch-branch", {
            "branch": branch,
            "restart": restart,
        })

        if result.get("success"):
            console.print(f"[green]✓ Branch switched successfully![/green]")
            console.print(f"Current branch: {result.get('current_branch')}")

            if result.get("git_output"):
                console.print("\n[bold]Git output:[/bold]")
                console.print(f"[dim]{result.get('git_output')}[/dim]")

            if restart and result.get("restarted"):
                console.print("\n[green]✓ Service restarted[/green]")
                console.print("[yellow]Note:[/yellow] The backend may take a few seconds to become available.")
            elif restart:
                console.print("\n[yellow]⚠ Service restart initiated but status unknown[/yellow]")
        else:
            error_console.print(f"[red]✗ Failed to switch branch[/red]")
            error_console.print(f"Error: {result.get('error', 'Unknown error')}")
            sys.exit(1)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# BACKUP COMMANDS
# ============================================================================


@system.group(name="backup")
def system_backup() -> None:
    """Database backup management commands."""


@system_backup.command(name="create")
@click.option("--description", "-d", help="Optional description of the backup")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def backup_create(ctx: click.Context, description: Optional[str], output: Optional[str]) -> None:
    """Create a new database backup.

    Example:
        aiops system backup create
        aiops system backup create --description "Before migration"
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        console.print("[yellow]Creating database backup...[/yellow]")
        result = client.create_backup(description=description)

        backup = result.get("backup", {})
        console.print(f"[green]✓[/green] {result.get('message', 'Backup created')}")

        if output_format == "table":
            console.print(f"\n[bold]Backup ID:[/bold] {backup.get('id')}")
            console.print(f"[bold]Filename:[/bold] {backup.get('filename')}")
            console.print(f"[bold]Size:[/bold] {backup.get('size_bytes', 0) / 1024 / 1024:.2f} MB")
            if backup.get("description"):
                console.print(f"[bold]Description:[/bold] {backup.get('description')}")
        else:
            format_output(result, output_format, console)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@system_backup.command(name="list")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def backup_list(ctx: click.Context, output: Optional[str]) -> None:
    """List all available backups.

    Example:
        aiops system backup list
        aiops system backup list --output json
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        backups = client.list_backups()

        if not backups:
            console.print("[yellow]No backups found.[/yellow]")
            return

        if output_format == "table":
            table = Table(title="Database Backups")
            table.add_column("ID", justify="right", style="cyan")
            table.add_column("Filename", style="green")
            table.add_column("Size", justify="right")
            table.add_column("Created At")
            table.add_column("Description", style="dim")

            for backup in backups:
                size_mb = backup.get("size_bytes", 0) / 1024 / 1024
                created_at = backup.get("created_at", "N/A")
                if created_at != "N/A":
                    # Format ISO datetime to readable format
                    from datetime import datetime
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    created_at = dt.strftime("%Y-%m-%d %H:%M")

                table.add_row(
                    str(backup.get("id")),
                    backup.get("filename", ""),
                    f"{size_mb:.2f} MB",
                    created_at,
                    backup.get("description") or "",
                )

            console.print(table)
            console.print(f"\n[dim]Total: {len(backups)} backup(s)[/dim]")
        else:
            format_output({"backups": backups}, output_format, console)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@system_backup.command(name="download")
@click.argument("backup_id", type=int)
@click.option("--output", "-o", help="Output file path (default: <filename>)")
@click.pass_context
def backup_download(ctx: click.Context, backup_id: int, output: Optional[str]) -> None:
    """Download a backup file.

    BACKUP_ID is the database ID of the backup (from 'aiops system backup list').

    Example:
        aiops system backup download 5
        aiops system backup download 5 --output /tmp/my_backup.tar.gz
    """
    client = get_client(ctx)

    try:
        # Get backup details to determine filename
        backup = client.get_backup(backup_id)
        filename = backup.get("filename", f"backup_{backup_id}.tar.gz")

        # Determine output path
        output_path = output or filename

        console.print(f"[yellow]Downloading backup {backup_id}...[/yellow]")
        client.download_backup(backup_id, output_path)

        console.print(f"[green]✓[/green] Backup downloaded to: {output_path}")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except Exception as exc:
        error_console.print(f"[red]Download failed:[/red] {exc}")
        sys.exit(1)


@system_backup.command(name="restore")
@click.argument("backup_id", type=int)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def backup_restore(ctx: click.Context, backup_id: int, yes: bool) -> None:
    """Restore the database from a backup.

    WARNING: This is a destructive operation that will replace the current database!

    BACKUP_ID is the database ID of the backup (from 'aiops system backup list').

    Example:
        aiops system backup restore 5
        aiops system backup restore 5 --yes
    """
    if not yes:
        console.print(
            "[bold red]WARNING:[/bold red] This will replace the current database!",
        )
        click.confirm("Are you sure you want to restore from this backup?", abort=True)

    client = get_client(ctx)

    try:
        console.print(f"[yellow]Restoring database from backup {backup_id}...[/yellow]")
        result = client.restore_backup(backup_id)

        console.print(f"[green]✓[/green] {result.get('message', 'Database restored')}")
        console.print("[yellow]Note:[/yellow] You may need to restart the application.")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# AGENTS COMMANDS
# ============================================================================


@cli.group()
def agents() -> None:
    """Agent context management commands."""


@agents.group(name="global")
def agents_global() -> None:
    """Manage global agent context."""


@agents_global.command(name="get")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "json", "yaml"]),
    help="Output format",
)
@click.pass_context
def agents_global_get(ctx: click.Context, output: Optional[str]) -> None:
    """Get the current global agent context."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        result = client.get_global_agent_context()

        if result.get("content") is None:
            console.print("[yellow]No global agent context set.[/yellow]")
            msg = result.get("message", "System will use AGENTS.md from repository.")
            console.print(msg)
        else:
            if output_format == "json":
                format_output(result, output_format, console)
            elif output_format == "yaml":
                format_output(result, output_format, console)
            else:
                # Table format - show metadata
                console.print("[bold]Global Agent Context[/bold]\n")
                updated_at = result.get("updated_at", "N/A")
                console.print(f"[yellow]Updated:[/yellow] {updated_at}")
                if result.get("updated_by"):
                    updated_by = result["updated_by"]
                    name = updated_by.get("name")
                    email = updated_by.get("email")
                    console.print(
                        f"[yellow]Updated by:[/yellow] {name} ({email})"
                    )
                console.print("\n[bold]Content:[/bold]")
                console.print(result.get("content", ""))

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@agents_global.command(name="set")
@click.option(
    "--file",
    "-f",
    "source_file",
    type=click.Path(exists=True),
    help="Read content from file",
)
@click.pass_context
def agents_global_set(ctx: click.Context, source_file: Optional[str]) -> None:
    """Set or update the global agent context.

    If --file is not provided, content will be read from stdin.
    """
    client = get_client(ctx)

    # Read content from file or stdin
    if source_file:
        with open(source_file, encoding="utf-8") as f:
            content = f.read()
    else:
        if sys.stdin.isatty():
            console.print(
                "[yellow]Reading content from stdin. "
                "Press Ctrl-D (Unix) or Ctrl-Z (Windows) to finish.[/yellow]"
            )
        content = sys.stdin.read()

    content = content.strip()
    if not content:
        error_console.print("[red]Error:[/red] Content cannot be empty")
        sys.exit(1)

    try:
        result = client.set_global_agent_context(content)
        msg = result.get("message", "Global agent context updated successfully")
        console.print(f"[green]✓[/green] {msg}")
        console.print(
            f"\n[yellow]Updated at:[/yellow] {result.get('updated_at', 'N/A')}"
        )

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@agents_global.command(name="clear")
@click.confirmation_option(
    prompt="Are you sure you want to clear the global agent context?"
)
@click.pass_context
def agents_global_clear(ctx: click.Context) -> None:
    """Clear the global agent context.

    This will cause the system to fall back to AGENTS.md from the repository.
    """
    client = get_client(ctx)

    try:
        result = client.delete_global_agent_context()
        msg = result.get("message", "Global agent context cleared")
        console.print(f"[green]✓[/green] {msg}")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# INTEGRATIONS COMMANDS
# ============================================================================


@cli.group()
def integrations() -> None:
    """Integration management commands."""


@integrations.command(name="list")
@click.option("--tenant", help="Filter by tenant ID, name, or slug")
@click.option("--provider", type=click.Choice(["github", "gitlab", "jira"]), help="Filter by provider")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), help="Output format")
@click.pass_context
def integrations_list(ctx: click.Context, tenant: Optional[str], provider: Optional[str], output: Optional[str]) -> None:
    """List integrations.

    Examples:
        aiops integrations list                    # List all integrations
        aiops integrations list --tenant floads    # List integrations for floads tenant
        aiops integrations list --provider gitlab  # List only GitLab integrations
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        # Resolve tenant name/slug to ID if provided
        tenant_id = None
        if tenant:
            tenant_id = resolve_tenant_id(client, tenant)

        integrations_data = client.list_integrations(tenant_id=tenant_id, provider=provider)

        if not integrations_data:
            console.print("[yellow]No integrations found[/yellow]")
            return

        # Show relevant columns
        columns = ["id", "provider", "name", "tenant_name", "base_url", "enabled"]
        format_output(integrations_data, output_format, console, title="Integrations", columns=columns)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# USER CREDENTIALS COMMANDS
# ============================================================================


@cli.group()
def credentials() -> None:
    """Manage personal integration credentials (for using your own tokens)."""


@credentials.command(name="list")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "json", "yaml"]),
    help="Output format",
)
@click.pass_context
def credentials_list(ctx: click.Context, output: Optional[str]) -> None:
    """List your personal integration credentials."""
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        result = client.get("auth/integration-credentials")
        credentials = result.get("credentials", [])

        if not credentials:
            console.print(
                "[yellow]No personal integration credentials configured[/yellow]"
            )
            console.print("\nUse 'aiops credentials set' to add your personal tokens")
            return

        format_output({"credentials": credentials}, output_format, console)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@credentials.command(name="set")
@click.option(
    "--integration-id",
    "-i",
    type=int,
    required=True,
    help="Integration ID (from tenants integrations list)",
)
@click.option(
    "--token",
    "-t",
    prompt=True,
    hide_input=True,
    help="Your personal API token/PAT",
)
@click.pass_context
def credentials_set(
    ctx: click.Context,
    integration_id: int,
    token: str,
) -> None:
    """Set your personal integration credential.

    This allows you to use your own GitLab/GitHub/Jira token instead of the bot's token
    when creating issues and comments via the CLI.

    Example:
        aiops credentials set --integration-id 5 --token glpat-xxx
    """
    client = get_client(ctx)

    try:
        result = client.post(
            "auth/integration-credentials",
            json={"integration_id": integration_id, "api_token": token},
        )
        message = result.get("message", "Credential saved successfully")
        console.print(f"[green]{message}[/green]")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@credentials.command(name="delete")
@click.argument("credential_id", type=int)
@click.pass_context
def credentials_delete(ctx: click.Context, credential_id: int) -> None:
    """Delete a personal integration credential."""
    client = get_client(ctx)

    try:
        client.delete(f"auth/integration-credentials/{credential_id}")
        console.print(f"[green]Credential {credential_id} deleted successfully[/green]")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# SSH KEYS COMMANDS
# ============================================================================


@cli.group(name="ssh-keys")
def ssh_keys() -> None:
    """Manage SSH keys for git operations (admin only)."""


@ssh_keys.command(name="list")
@click.option(
    "--tenant",
    "-t",
    type=int,
    help="Filter by tenant ID",
)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "json", "yaml"]),
    help="Output format",
)
@click.pass_context
def ssh_keys_list(
    ctx: click.Context, tenant: Optional[int], output: Optional[str]
) -> None:
    """List all SSH keys.

    Shows both filesystem keys and database-encrypted keys.
    Database keys are marked with [DB] prefix.
    """
    client = get_client(ctx)
    config: Config = ctx.obj["config"]
    output_format = output or config.output_format

    try:
        params = {}
        if tenant:
            params["tenant_id"] = tenant

        result = client.get("admin/ssh-keys", params=params)
        keys = result.get("ssh_keys", [])

        if not keys:
            console.print("[yellow]No SSH keys configured[/yellow]")
            console.print("\nUse 'aiops ssh-keys add' to add a key")
            return

        if output_format == "table":
            table = Table(title="SSH Keys")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Tenant", style="magenta")
            table.add_column("Type", style="yellow")
            table.add_column("Created", style="blue")

            for key in keys:
                key_type = "[DB]" if key.get("encrypted_private_key") else "Filesystem"
                table.add_row(
                    str(key.get("id", "")),
                    key.get("name", ""),
                    key.get("tenant_name", ""),
                    key_type,
                    key.get("created_at", ""),
                )

            console.print(table)
        else:
            format_output({"ssh_keys": keys}, output_format, console)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@ssh_keys.command(name="add")
@click.option(
    "--name",
    "-n",
    required=True,
    help="Name for the SSH key",
)
@click.option(
    "--tenant",
    "-t",
    type=int,
    required=True,
    help="Tenant ID to associate key with",
)
@click.option(
    "--private-key-file",
    "-f",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to private key file (will be encrypted and stored in database)",
)
@click.option(
    "--public-key-file",
    "-p",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to public key file (optional)",
)
@click.pass_context
def ssh_keys_add(
    ctx: click.Context,
    name: str,
    tenant: int,
    private_key_file: str,
    public_key_file: Optional[str],
) -> None:
    """Add an SSH key and encrypt it in the database.

    The private key will be encrypted using SSH_KEY_ENCRYPTION_KEY from .env
    and stored in the database. The original file is not modified.

    Example:
        aiops ssh-keys add --name "my-deploy-key" --tenant 1 --private-key-file ~/.ssh/id_ed25519
    """
    client = get_client(ctx)

    try:
        # Read private key
        with open(private_key_file, "r") as f:
            private_key_content = f.read()

        # Read public key if provided
        public_key_content = None
        if public_key_file:
            with open(public_key_file, "r") as f:
                public_key_content = f.read()

        # Send to API
        result = client.post(
            "admin/ssh-keys",
            json={
                "name": name,
                "tenant_id": tenant,
                "private_key_content": private_key_content,
                "public_key_content": public_key_content,
            },
        )

        key_id = result.get("id")
        console.print(f"[green]SSH key '{name}' added successfully (ID: {key_id})[/green]")
        console.print("[yellow]Private key encrypted and stored in database[/yellow]")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except OSError as exc:
        error_console.print(f"[red]Error reading key file:[/red] {exc}")
        sys.exit(1)


@ssh_keys.command(name="delete")
@click.argument("key_id", type=int)
@click.confirmation_option(prompt="Are you sure you want to delete this SSH key?")
@click.pass_context
def ssh_keys_delete(ctx: click.Context, key_id: int) -> None:
    """Delete an SSH key from the database.

    This will remove the encrypted key from the database.
    Projects using this key will fall back to other available keys.
    """
    client = get_client(ctx)

    try:
        client.delete(f"admin/ssh-keys/{key_id}")
        console.print(f"[green]SSH key {key_id} deleted successfully[/green]")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@ssh_keys.command(name="migrate")
@click.option(
    "--key-id",
    "-k",
    type=int,
    required=True,
    help="SSH key ID to migrate",
)
@click.option(
    "--private-key-file",
    "-f",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to private key file on filesystem",
)
@click.pass_context
def ssh_keys_migrate(
    ctx: click.Context, key_id: int, private_key_file: str
) -> None:
    """Migrate an existing filesystem SSH key to encrypted database storage.

    This reads the private key from the filesystem and stores it encrypted
    in the database. The original file is not modified.

    Example:
        aiops ssh-keys migrate --key-id 5 --private-key-file /path/to/key
    """
    client = get_client(ctx)

    try:
        # Read private key
        with open(private_key_file, "r") as f:
            private_key_content = f.read()

        # Send to API
        result = client.post(
            f"admin/ssh-keys/{key_id}/migrate",
            json={"private_key_content": private_key_content},
        )

        console.print(f"[green]{result.get('message', 'Key migrated successfully')}[/green]")
        console.print("[yellow]Private key encrypted and stored in database[/yellow]")

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except OSError as exc:
        error_console.print(f"[red]Error reading key file:[/red] {exc}")
        sys.exit(1)


# ============================================================================
# ACTIVITY COMMANDS
# ============================================================================


@cli.group(name="activity")
def activity() -> None:
    """Activity log commands."""


@activity.command(name="list")
@click.option("--user-id", "-u", type=int, help="Filter by user ID")
@click.option("--action-type", "-a", help="Filter by action type (e.g., git.pull, issue.create)")
@click.option("--resource-type", "-r", help="Filter by resource type (e.g., project, issue)")
@click.option("--status", "-s", type=click.Choice(["success", "failure", "pending"]), help="Filter by status")
@click.option("--source", type=click.Choice(["web", "cli"]), help="Filter by source")
@click.option("--limit", "-l", type=int, default=50, help="Maximum number of activities to return (default: 50)")
@click.option("--output", "-o", type=click.Choice(["table", "json", "yaml"]), default="table", help="Output format")
@click.pass_context
def activity_list(
    ctx: click.Context,
    user_id: Optional[int],
    action_type: Optional[str],
    resource_type: Optional[str],
    status: Optional[str],
    source: Optional[str],
    limit: int,
    output: str,
) -> None:
    """List recent activity log entries.

    Examples:
        # List last 50 activities
        aiops activity list

        # List CLI activities only
        aiops activity list --source cli

        # List failed operations
        aiops activity list --status failure

        # List git operations
        aiops activity list --action-type git.pull

        # Export to JSON
        aiops activity list --limit 100 --output json
    """
    try:
        client = get_client(ctx)

        # Build query parameters
        params = {"limit": limit}
        if user_id:
            params["user_id"] = user_id
        if action_type:
            params["action_type"] = action_type
        if resource_type:
            params["resource_type"] = resource_type
        if status:
            params["status"] = status
        if source:
            params["source"] = source

        # Make API request to list activities
        result = client.get("/activities", params=params)

        activities = result.get("activities", [])
        count = result.get("count", 0)

        if output == "json":
            import json
            console.print(json.dumps(activities, indent=2))
        elif output == "yaml":
            import yaml
            console.print(yaml.dump(activities, default_flow_style=False))
        else:
            # Table output
            if not activities:
                console.print("[yellow]No activities found matching the filters.[/yellow]")
                return

            table = Table(title=f"Recent Activities ({count} shown)")
            table.add_column("Time", style="cyan", no_wrap=True)
            table.add_column("User", no_wrap=True)
            table.add_column("Action", no_wrap=True)
            table.add_column("Resource", no_wrap=True)
            table.add_column("St", justify="center", no_wrap=True)
            table.add_column("Src", style="dim", no_wrap=True)

            for activity in activities:
                # Format timestamp - compact format (MMM DD HH:MM)
                timestamp = activity.get("timestamp", "")
                if timestamp:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%b %d %H:%M")
                else:
                    time_str = "N/A"

                # Format user - extract name from email for brevity
                user_email = activity.get("user_email", "")
                if user_email and "@" in user_email:
                    user = user_email.split("@")[0]
                elif user_email:
                    user = user_email
                else:
                    user = f"User {activity.get('user_id', 'N/A')}"

                # Format resource - compact format
                resource_type = activity.get("resource_type", "")
                resource_name = activity.get("resource_name", "")
                if resource_name:
                    # Just show the name without type prefix
                    resource = resource_name[:16]
                else:
                    resource = resource_type[:16] if resource_type else "-"

                # Status - use colored symbols
                status = activity.get("status", "")
                status_symbol = {
                    "success": "[green]✓[/green]",
                    "failure": "[red]✗[/red]",
                    "pending": "[yellow]○[/yellow]",
                }.get(status, "?")

                # Source - compact icons
                source = activity.get("source", "")
                source_icon = "CLI" if source == "cli" else "Web"

                table.add_row(
                    time_str,
                    user[:10],
                    activity.get("action_type", "")[:14],
                    resource,
                    status_symbol,
                    source_icon,
                )

            console.print(table)

    except APIError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
