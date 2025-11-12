"""introduce tenant integrations and external issues

Revision ID: 4a2a1640babc
Revises:
Create Date: 2025-10-21 21:15:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4a2a1640babc"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenant_integrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("api_token", sa.Text(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tenant_integrations_tenant_id"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tenant_integration_name"),
    )

    op.create_table(
        "project_integrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("external_identifier", sa.String(length=255), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["tenant_integrations.id"],
            name="fk_project_integrations_integration_id",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_project_integrations_project_id"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id", "project_id", name="uq_project_integration_unique"
        ),
    )

    op.create_table(
        "external_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("project_integration_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=128), nullable=True),
        sa.Column("assignee", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("external_updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_integration_id"],
            ["project_integrations.id"],
            name="fk_external_issues_project_integration_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_integration_id", "external_id", name="uq_external_issue_identifier"
        ),
    )


def downgrade():
    op.drop_table("external_issues")
    op.drop_table("project_integrations")
    op.drop_table("tenant_integrations")
