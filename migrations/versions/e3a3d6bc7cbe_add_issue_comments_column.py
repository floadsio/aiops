"""Add normalized comment cache to external issues.

Revision ID: e3a3d6bc7cbe
Revises: 443f6eca1717
Create Date: 2025-11-15 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e3a3d6bc7cbe"
down_revision = "443f6eca1717"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("external_issues", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "comments",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("external_issues", schema=None) as batch_op:
        batch_op.drop_column("comments")
