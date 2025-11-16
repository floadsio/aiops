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
        console.print(
            f"[yellow]Warning:[/yellow] Multiple projects named '{project_identifier}' found, using first match",
            file=sys.stderr,
        )

    return matching_projects[0]["id"]


def resolve_tenant_id(client: APIClient, tenant_identifier: str) -> int:
    """Resolve tenant name or ID to numeric ID.

    Args:
        client: API client
        tenant_identifier: Tenant ID (numeric string) or slug

    Returns:
        Tenant ID as integer

    Raises:
        click.ClickException: If tenant not found or multiple matches
    """
    # Check if it's a numeric ID
    if tenant_identifier.isdigit():
        return int(tenant_identifier)

    # Look up tenant by slug (case-insensitive)
    tenants = client.list_tenants()
    matching_tenants = [
        t for t in tenants if t.get("slug", "").lower() == tenant_identifier.lower()
    ]

    if not matching_tenants:
        raise click.ClickException(f"Tenant '{tenant_identifier}' not found")

    if len(matching_tenants) > 1:
        console.print(
            f"[yellow]Warning:[/yellow] Multiple tenants with slug '{tenant_identifier}' found, using first match",
            file=sys.stderr,
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
        sys.exit(1)


# ============================================================================
# ISSUES COMMANDS
# ============================================================================


@cli.group()
def issues() -> None:
    """Issue management commands."""


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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
        sys.exit(1)


@issues.command(name="comment")
@click.argument("issue_id", type=int)
@click.argument("body")
@click.pass_context
def issues_comment(ctx: click.Context, issue_id: int, body: str) -> None:
    """Add comment to issue."""
    client = get_client(ctx)

    try:
        client.add_issue_comment(issue_id, body)
        console.print(f"[green]Comment added to issue {issue_id}![/green]")
    except APIError as exc:
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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
        console.print(f"[red]Error:[/red] {exc}", file=sys.stderr)
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


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
