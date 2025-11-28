"""Add yadm dotfile support to Project and User models

Revision ID: c8e3f7a2b9d1
Revises: f366ffba1cd8
Create Date: 2025-11-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8e3f7a2b9d1'
down_revision = 'f366ffba1cd8'
branch_labels = None
depends_on = None


def upgrade():
    # Add yadm/dotfile configuration columns to projects table
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dotfile_repo_url', sa.String(512), nullable=True))
        batch_op.add_column(sa.Column('dotfile_branch', sa.String(128), nullable=True, server_default='main'))
        batch_op.add_column(sa.Column('dotfile_enabled', sa.Boolean(), nullable=False, server_default='0'))

    # Add yadm/dotfile configuration columns to users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('personal_dotfile_repo_url', sa.String(512), nullable=True))
        batch_op.add_column(sa.Column('personal_dotfile_branch', sa.String(128), nullable=True))
        batch_op.add_column(sa.Column('gpg_private_key_encrypted', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('gpg_key_id', sa.String(16), nullable=True))


def downgrade():
    # Remove yadm/dotfile configuration columns from projects table
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('dotfile_enabled')
        batch_op.drop_column('dotfile_branch')
        batch_op.drop_column('dotfile_repo_url')

    # Remove yadm/dotfile configuration columns from users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('gpg_key_id')
        batch_op.drop_column('gpg_private_key_encrypted')
        batch_op.drop_column('personal_dotfile_branch')
        batch_op.drop_column('personal_dotfile_repo_url')
