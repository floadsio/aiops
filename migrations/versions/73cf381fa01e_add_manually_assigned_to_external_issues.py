"""Add manually_assigned column to external_issues.

Revision ID: 73cf381fa01e
Revises: c2e2fc221f62
Create Date: 2025-12-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "73cf381fa01e"
down_revision = "c2e2fc221f62"
branch_labels = None
depends_on = None


def upgrade():
    """Add manually_assigned column to track issues moved between projects."""
    op.add_column(
        "external_issues",
        sa.Column(
            "manually_assigned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    """Remove manually_assigned column."""
    op.drop_column("external_issues", "manually_assigned")
