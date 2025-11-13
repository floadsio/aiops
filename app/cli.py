import os
import shutil
from pathlib import Path
from typing import Optional

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy.orm import selectinload

from .extensions import db
from .models import Project, ProjectIntegration, SSHKey, Tenant, TenantIntegration, User
from .security import hash_password
from .services.issues import (
    IssueSyncError,
    create_issue_for_project_integration,
    sync_tenant_integrations,
)
from .services.key_service import compute_fingerprint, format_private_key_path
from .version import __version__


@click.command("db_init")
@with_appcontext
def db_init_command() -> None:
    """Initialize the database tables."""
    db.create_all()
    click.echo("Database initialized.")


@click.command("create-admin")
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_admin_command(email: str, password: str) -> None:
    """Create an administrator account."""
    if User.query.filter_by(email=email).first():
        raise click.ClickException("User already exists.")

    user = User(
        email=email,
        name="Administrator",
        password_hash=hash_password(password),
        is_admin=True,
    )
    db.session.add(user)
    db.session.commit()
    click.echo(f"Admin user {email} created.")


@click.command("seed-data")
@click.option(
    "--owner-email", default=None, help="Email of the user who owns the seed project."
)
@with_appcontext
def seed_data_command(owner_email: Optional[str]) -> None:
    """Seed initial tenant and project data."""
    seed_entries = [
        {
            "tenant": {"name": "dcx", "description": "Seed tenant dcx"},
            "project": {
                "name": "flamelet-dcx",
                "repo_url": "git@ssh.dev.azure.com:v3/vaikoon/flow.swiss%20DevOps/flamelet-dcx",
                "default_branch": "main",
                "description": "Seed project for dcx tenant",
            },
        },
        {
            "tenant": {"name": "iwf", "description": "Seed tenant iwf"},
            "project": {
                "name": "flamelet-iwf",
                "repo_url": "git@git.iwf.io:infrastructure/flamelet-iwf.git",
                "default_branch": "main",
                "description": "Seed project for iwf tenant",
            },
        },
        {
            "tenant": {"name": "kbe", "description": "Seed tenant kbe"},
            "project": {
                "name": "flamelet-kbe",
                "repo_url": "ssh://git@gitlab.kumbe.it:19022/kumbe/devops/flamelet-kbe.git",
                "default_branch": "main",
                "description": "Seed project for kbe tenant",
            },
        },
    ]

    email = owner_email or os.getenv("AIOPS_ADMIN_EMAIL")
    if not email:
        raise click.ClickException(
            "Owner email not provided. Pass --owner-email or set AIOPS_ADMIN_EMAIL."
        )

    owner = User.query.filter_by(email=email).first()
    if owner is None:
        raise click.ClickException(f"No user found with email {email}.")

    storage_root = Path(current_app.config["REPO_STORAGE_PATH"])
    storage_root.mkdir(parents=True, exist_ok=True)

    created = 0
    for entry in seed_entries:
        seed_tenant = entry["tenant"]
        seed_project = entry["project"]

        tenant = Tenant.query.filter_by(name=seed_tenant["name"]).first()
        if tenant is None:
            tenant = Tenant(**seed_tenant)
            db.session.add(tenant)
            click.echo(f"Created tenant '{tenant.name}'.")

        db.session.flush()

        project = Project.query.filter_by(
            name=seed_project["name"], tenant_id=tenant.id
        ).first()
        if project is None:
            local_path = storage_root / seed_project["name"].replace(" ", "-")
            project = Project(
                **seed_project,
                tenant=tenant,
                owner=owner,
                local_path=str(local_path),
            )
            db.session.add(project)
            created += 1
            click.echo(
                f"Created project '{project.name}' for tenant '{tenant.name}' "
                f"at {local_path}."
            )
        else:
            click.echo(
                f"Seed project '{seed_project['name']}' already present for tenant '{tenant.name}'."
            )

    db.session.commit()
    click.echo(f"Seed data applied. {created} new project(s) created.")


@click.command("seed-identities")
@click.option(
    "--owner-email", required=True, help="Email of the user who owns the keys."
)
@click.option(
    "--source-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory containing syseng SSH key pairs (defaults to ~/.ssh/syseng).",
)
@with_appcontext
def seed_identities_command(owner_email: str, source_dir: Optional[Path]) -> None:
    """Seed SSH identities from a local directory into the database."""
    owner = User.query.filter_by(email=owner_email).first()
    if owner is None:
        raise click.ClickException(f"No user found with email {owner_email}.")

    key_root = source_dir or (Path.home() / ".ssh" / "syseng")
    if not key_root.exists():
        raise click.ClickException(f"Key directory {key_root} does not exist.")

    dest_dir = Path(current_app.instance_path) / "keys"
    dest_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    for priv_file in sorted(key_root.iterdir()):
        if priv_file.is_dir() or priv_file.name.endswith(".pub"):
            continue

        pub_file = priv_file.parent / f"{priv_file.name}.pub"
        if not pub_file.exists():
            click.echo(f"Skipping {priv_file.name}: missing public key.", err=True)
            continue

        public_key = pub_file.read_text().strip()
        try:
            fingerprint = compute_fingerprint(public_key)
        except Exception as exc:  # noqa: BLE001
            click.echo(
                f"Skipping {priv_file.name}: invalid public key ({exc}).", err=True
            )
            continue

        parts = priv_file.name.split("-")
        if len(parts) >= 3 and parts[-1] == "syseng":
            core_parts = parts[1:-1]
        else:
            core_parts = parts[1:]
        tenant_slug = core_parts[0] if core_parts else parts[0]
        key_label_suffix = "-".join(core_parts) if core_parts else priv_file.stem
        key_name = f"syseng-{key_label_suffix}"

        tenant = Tenant.query.filter_by(name=tenant_slug).first()
        if tenant is None:
            tenant = Tenant(
                name=tenant_slug,
                description=f"Seeded tenant derived from key {priv_file.name}",
            )
            db.session.add(tenant)
            click.echo(f"Created tenant '{tenant.name}'.")

        ssh_key = SSHKey.query.filter_by(fingerprint=fingerprint).first()
        if ssh_key is None:
            ssh_key = SSHKey(
                name=key_name,
                public_key=public_key,
                fingerprint=fingerprint,
                user=owner,
                tenant=tenant,
            )
            db.session.add(ssh_key)
        else:
            ssh_key.name = key_name
            ssh_key.public_key = public_key
            ssh_key.user = owner
            ssh_key.tenant = tenant

        dest_path = dest_dir / priv_file.name
        shutil.copy(priv_file, dest_path)
        os.chmod(dest_path, 0o600)
        ssh_key.private_key_path = format_private_key_path(dest_path)
        processed += 1

    db.session.commit()
    click.echo(f"Seeded {processed} SSH identities into the database.")


@click.command("sync-issues")
@click.option(
    "--tenant-id", type=int, default=None, help="Limit synchronization to a tenant ID."
)
@click.option(
    "--integration-id",
    type=int,
    default=None,
    help="Limit synchronization to a specific tenant integration ID.",
)
@with_appcontext
def sync_issues_command(
    tenant_id: Optional[int], integration_id: Optional[int]
) -> None:
    """Pull external issues for configured project integrations."""
    if tenant_id is not None and integration_id is not None:
        integration = TenantIntegration.query.get(integration_id)
        if integration is None or integration.tenant_id != tenant_id:
            raise click.ClickException(
                "Integration does not belong to the provided tenant."
            )

    query = (
        ProjectIntegration.query.options(
            selectinload(ProjectIntegration.project),
            selectinload(ProjectIntegration.integration).selectinload(
                TenantIntegration.tenant
            ),
        )
        .join(ProjectIntegration.integration)
        .filter(TenantIntegration.enabled.is_(True))
    )

    if tenant_id is not None:
        query = query.filter(TenantIntegration.tenant_id == tenant_id)
    if integration_id is not None:
        query = query.filter(ProjectIntegration.integration_id == integration_id)

    project_integrations = query.all()
    if not project_integrations:
        click.echo("No project integrations matched the filters.")
        return

    try:
        results = sync_tenant_integrations(project_integrations)
    except IssueSyncError as exc:
        raise click.ClickException(f"Issue synchronization failed: {exc}") from exc

    for project_integration in project_integrations:
        tenant_name = (
            project_integration.integration.tenant.name
            if project_integration.integration.tenant
            else "Unknown tenant"
        )
        project_name = (
            project_integration.project.name
            if project_integration.project
            else "Unknown project"
        )
        provider = project_integration.integration.provider
        count = len(results.get(project_integration.id, []))
        click.echo(
            f"[{provider}] {tenant_name} -> {project_name} - fetched {count} issue(s)."
        )

    click.echo("Issue synchronization completed.")


@click.command("create-issue")
@click.option(
    "--project-integration-id",
    type=int,
    required=True,
    help="ID of the project integration to create the issue for.",
)
@click.option("--summary", prompt=True, help="Issue summary/title.")
@click.option("--description", default="", help="Issue description (optional).")
@click.option(
    "--issue-type",
    default=None,
    help="Issue type/name (provider-specific). Defaults to the integration's configured type.",
)
@click.option(
    "--label",
    "labels",
    multiple=True,
    help="Label to assign to the issue (can be repeated).",
)
@with_appcontext
def create_issue_command(
    project_integration_id: int,
    summary: str,
    description: str,
    issue_type: Optional[str],
    labels: tuple[str, ...],
) -> None:
    """Create a new external issue for a linked project integration."""
    project_integration = ProjectIntegration.query.options(
        selectinload(ProjectIntegration.integration).selectinload(
            TenantIntegration.tenant
        ),
        selectinload(ProjectIntegration.project),
    ).get(project_integration_id)
    if project_integration is None:
        raise click.ClickException("Project integration not found.")

    integration = project_integration.integration
    if integration is None:
        raise click.ClickException(
            "Project integration is missing its parent integration."
        )

    clean_summary = (summary or "").strip()
    if not clean_summary:
        raise click.ClickException("Issue summary cannot be empty.")

    clean_description = description.strip() if description else None
    clean_labels = [label.strip() for label in labels if label.strip()]

    try:
        payload = create_issue_for_project_integration(
            project_integration,
            summary=clean_summary,
            description=clean_description,
            issue_type=issue_type.strip() if issue_type else None,
            labels=clean_labels or None,
        )
    except IssueSyncError as exc:
        raise click.ClickException(f"Issue creation failed: {exc}") from exc

    tenant_name = integration.tenant.name if integration.tenant else "Unknown tenant"
    project_name = (
        project_integration.project.name
        if project_integration.project
        else "Unknown project"
    )
    click.echo(
        f"[{integration.provider}] {tenant_name} -> {project_name}: created issue {payload.external_id}."
    )
    if payload.url:
        click.echo(f"Issue URL: {payload.url}")


@click.command("version")
def version_command() -> None:
    """Display the aiops version."""
    click.echo(__version__)


@click.command("init-workspace")
@click.option("--user-email", required=True, help="Email of the user")
@click.option("--project-id", required=True, type=int, help="ID of the project")
@with_appcontext
def init_workspace_command(user_email: str, project_id: int) -> None:
    """Initialize a workspace for a user and project."""
    from .services.workspace_service import WorkspaceError, initialize_workspace

    user = User.query.filter_by(email=user_email).first()
    if not user:
        raise click.ClickException(f"User with email {user_email} not found.")

    project = Project.query.get(project_id)
    if not project:
        raise click.ClickException(f"Project with ID {project_id} not found.")

    click.echo(f"Initializing workspace for {user.email} and project {project.name}...")
    try:
        workspace_path = initialize_workspace(project, user)
        click.echo(f"Workspace initialized at: {workspace_path}")
    except WorkspaceError as exc:
        raise click.ClickException(str(exc)) from exc


@click.command("test-sudo")
@click.option("--user-email", help="Email of user to test sudo access for")
@with_appcontext
def test_sudo_command(user_email: Optional[str] = None) -> None:
    """Test sudo configuration and permissions for workspace operations.

    This command checks:
    - Passwordless sudo access for the Flask app user
    - Ability to run commands as target Linux users
    - Directory permissions for workspace access
    - Git safe directory configuration

    If --user-email is provided, tests sudo access for that specific user.
    Otherwise, tests sudo configuration in general.
    """
    import pwd
    import subprocess

    from .services.linux_users import resolve_linux_username
    from .services.sudo_service import SudoError, run_as_user, test_path

    click.echo("=== Testing Sudo Configuration ===\n")

    # Test 1: Check current user
    current_user = pwd.getpwuid(os.getuid()).pw_name
    click.echo(f"Current user: {current_user}")

    # Test 2: Check passwordless sudo
    click.echo("\n1. Testing passwordless sudo access...")
    try:
        result = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            click.echo("   ✓ Passwordless sudo is configured")
        else:
            click.echo("   ✗ Passwordless sudo is NOT configured")
            click.echo("     Configure /etc/sudoers.d/aiops with:")
            click.echo(f"     {current_user} ALL=(ALL) NOPASSWD: ALL")
            return
    except Exception as e:
        click.echo(f"   ✗ Error testing sudo: {e}")
        return

    # Test 3: If user specified, test sudo access for that user
    if user_email:
        click.echo(f"\n2. Testing sudo access for user: {user_email}")

        user = User.query.filter_by(email=user_email).first()
        if not user:
            raise click.ClickException(f"User with email {user_email} not found.")

        linux_username = resolve_linux_username(user)
        if not linux_username:
            click.echo(f"   ✗ No Linux username mapping found for {user_email}")
            return

        click.echo(f"   Linux username: {linux_username}")

        # Test sudo access as the target user
        try:
            result = run_as_user(linux_username, ["whoami"], timeout=5)
            if result.success and linux_username in result.stdout:
                click.echo(f"   ✓ Can run commands as {linux_username}")
            else:
                click.echo(f"   ✗ Failed to run commands as {linux_username}")
                return
        except SudoError as e:
            click.echo(f"   ✗ Error: {e}")
            return

        # Test workspace directory access
        from .services.workspace_service import get_workspace_path

        projects = Project.query.limit(1).all()
        if projects:
            project = projects[0]
            workspace_path = get_workspace_path(project, user)

            if workspace_path:
                click.echo(f"\n3. Testing workspace access at: {workspace_path}")

                # Check if parent directories have execute permissions
                home_dir = workspace_path.parent.parent
                workspace_root = workspace_path.parent

                for path in [home_dir, workspace_root]:
                    try:
                        # Try to access as current user
                        if path.exists():
                            perms = oct(path.stat().st_mode)[-3:]
                            if int(perms[2]) & 1:  # Check "other" execute bit
                                click.echo(f"   ✓ {path}: o+x permission set")
                            else:
                                click.echo(f"   ✗ {path}: missing o+x permission")
                                click.echo(f"     Run: chmod o+rx {path}")
                    except PermissionError:
                        click.echo(f"   ✗ {path}: Permission denied (cannot check)")

                # Test if we can check workspace via sudo
                if test_path(linux_username, str(workspace_path)):
                    click.echo("   ✓ Can access workspace via sudo")
                else:
                    click.echo("   ℹ Workspace not yet initialized")

        # Test git safe directory configuration
        click.echo("\n4. Testing git safe directory configuration...")
        try:
            result = subprocess.run(
                ["git", "config", "--global", "--get-all", "safe.directory"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                safe_dirs = result.stdout.strip().split("\n")
                click.echo(f"   Git safe directories configured: {len(safe_dirs)}")
                for safe_dir in safe_dirs[:5]:  # Show first 5
                    click.echo(f"     - {safe_dir}")
            else:
                click.echo("   ⚠ No git safe directories configured")
                click.echo("     This may cause 'dubious ownership' errors")
                click.echo("     Run: sudo -u syseng git config --global --add safe.directory '*'")
        except Exception as e:
            click.echo(f"   ✗ Error checking git config: {e}")

    else:
        # General tests without specific user
        click.echo("\n2. General sudo configuration looks good")
        click.echo("   Use --user-email to test specific user access")

    click.echo("\n=== Sudo Configuration Test Complete ===")


def register_cli_commands(app) -> None:
    app.cli.add_command(db_init_command)
    app.cli.add_command(create_admin_command)
    app.cli.add_command(seed_data_command)
    app.cli.add_command(seed_identities_command)
    app.cli.add_command(sync_issues_command)
    app.cli.add_command(create_issue_command)
    app.cli.add_command(version_command)
    app.cli.add_command(init_workspace_command)
    app.cli.add_command(test_sudo_command)
