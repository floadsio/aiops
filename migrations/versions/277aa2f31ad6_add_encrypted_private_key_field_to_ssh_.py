"""Add encrypted_private_key field to ssh_keys table

Revision ID: 277aa2f31ad6
Revises: ad3a6520c17e
Create Date: 2025-11-19 16:13:04.494239

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '277aa2f31ad6'
down_revision = 'ad3a6520c17e'
branch_labels = None
depends_on = None


def upgrade():
    # Add encrypted_private_key column to ssh_keys table
    op.add_column('ssh_keys', sa.Column('encrypted_private_key', sa.LargeBinary(), nullable=True))


def downgrade():
    # Remove encrypted_private_key column from ssh_keys table
    op.drop_column('ssh_keys', 'encrypted_private_key')
