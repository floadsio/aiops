"""Add optional SSH key association to projects.

Revision ID: ba3ce5bf8b2a
Revises: 9ed76e12b271
Create Date: 2025-02-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ba3ce5bf8b2a"
down_revision = "9ed76e12b271"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ssh_key_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_projects_ssh_key_id",
            "ssh_keys",
            ["ssh_key_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_constraint("fk_projects_ssh_key_id", type_="foreignkey")
        batch_op.drop_column("ssh_key_id")
