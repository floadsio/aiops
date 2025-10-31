"""add private key path and tenant to ssh keys

Revision ID: 9ed76e12b271
Revises: 4a2a1640babc
Create Date: 2025-10-21 16:24:27.957480

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9ed76e12b271"
down_revision = "4a2a1640babc"
branch_labels = None
depends_on = None


def _column_missing(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name not in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade():
    if _column_missing("ssh_keys", "private_key_path"):
        op.add_column("ssh_keys", sa.Column("private_key_path", sa.String(length=512), nullable=True))
    if _column_missing("ssh_keys", "tenant_id"):
        op.add_column("ssh_keys", sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_ssh_keys_tenant_id",
            "ssh_keys",
            "tenants",
            ["tenant_id"],
            ["id"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {col["name"] for col in inspector.get_columns("ssh_keys")}
    if "tenant_id" in column_names:
        op.drop_constraint("fk_ssh_keys_tenant_id", "ssh_keys", type_="foreignkey")
        op.drop_column("ssh_keys", "tenant_id")
    if "private_key_path" in column_names:
        op.drop_column("ssh_keys", "private_key_path")

