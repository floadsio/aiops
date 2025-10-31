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
from .services.key_service import compute_fingerprint


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
@click.option("--owner-email", default=None, help="Email of the user who owns the seed project.")
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

        project = Project.query.filter_by(name=seed_project["name"], tenant_id=tenant.id).first()
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
@click.option("--owner-email", required=True, help="Email of the user who owns the keys.")
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
            click.echo(f"Skipping {priv_file.name}: invalid public key ({exc}).", err=True)
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
        ssh_key.private_key_path = str(dest_path)
        processed += 1

    db.session.commit()
    click.echo(f"Seeded {processed} SSH identities into the database.")


@click.command("sync-issues")
@click.option("--tenant-id", type=int, default=None, help="Limit synchronization to a tenant ID.")
@click.option(
    "--integration-id",
    type=int,
    default=None,
    help="Limit synchronization to a specific tenant integration ID.",
)
@with_appcontext
def sync_issues_command(tenant_id: Optional[int], integration_id: Optional[int]) -> None:
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
            selectinload(ProjectIntegration.integration).selectinload(TenantIntegration.tenant),
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
        project_name = project_integration.project.name if project_integration.project else "Unknown project"
        provider = project_integration.integration.provider
        count = len(results.get(project_integration.id, []))
        click.echo(f"[{provider}] {tenant_name} -> {project_name} - fetched {count} issue(s).")

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
        selectinload(ProjectIntegration.integration).selectinload(TenantIntegration.tenant),
        selectinload(ProjectIntegration.project),
    ).get(project_integration_id)
    if project_integration is None:
        raise click.ClickException("Project integration not found.")

    integration = project_integration.integration
    if integration is None:
        raise click.ClickException("Project integration is missing its parent integration.")

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

    tenant_name = (
        integration.tenant.name if integration.tenant else "Unknown tenant"
    )
    project_name = project_integration.project.name if project_integration.project else "Unknown project"
    click.echo(
        f"[{integration.provider}] {tenant_name} -> {project_name}: created issue {payload.external_id}."
    )
    if payload.url:
        click.echo(f"Issue URL: {payload.url}")


def register_cli_commands(app) -> None:
    app.cli.add_command(db_init_command)
    app.cli.add_command(create_admin_command)
    app.cli.add_command(seed_data_command)
    app.cli.add_command(seed_identities_command)
    app.cli.add_command(sync_issues_command)
    app.cli.add_command(create_issue_command)
