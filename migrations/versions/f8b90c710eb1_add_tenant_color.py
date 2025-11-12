"""Add tenant color field for UI accents.

Revision ID: f8b90c710eb1
Revises: ba3ce5bf8b2a
Create Date: 2025-02-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f8b90c710eb1"
down_revision = "ba3ce5bf8b2a"
branch_labels = None
depends_on = None

DEFAULT_COLOR = "#2563eb"


def upgrade() -> None:
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "color",
                sa.String(length=16),
                nullable=False,
                server_default=DEFAULT_COLOR,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.drop_column("color")
