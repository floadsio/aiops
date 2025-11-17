"""add per-project credential overrides to project_integrations

Revision ID: d8577dd97836
Revises: 2023de339b1a
Create Date: 2025-11-17 14:22:30.872086

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8577dd97836'
down_revision = '2023de339b1a'
branch_labels = None
depends_on = None


def upgrade():
    # Add override credential fields to project_integrations table
    op.add_column(
        "project_integrations",
        sa.Column("override_api_token", sa.Text(), nullable=True),
    )
    op.add_column(
        "project_integrations",
        sa.Column("override_base_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "project_integrations",
        sa.Column("override_settings", sa.JSON(), nullable=True),
    )


def downgrade():
    # Remove override credential fields from project_integrations table
    op.drop_column("project_integrations", "override_settings")
    op.drop_column("project_integrations", "override_base_url")
    op.drop_column("project_integrations", "override_api_token")
