"""Refactor yadm to use global configuration instead of per-project

Revision ID: 00c220ad7017
Revises: c8e3f7a2b9d1
Create Date: 2025-11-28 11:42:28.127683

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '00c220ad7017'
down_revision = 'c8e3f7a2b9d1'
branch_labels = None
depends_on = None


def upgrade():
    # Remove per-project dotfile configuration (now using global DOTFILE_REPO_URL env var)
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('dotfile_enabled')
        batch_op.drop_column('dotfile_branch')
        batch_op.drop_column('dotfile_repo_url')


def downgrade():
    # Restore per-project dotfile configuration fields
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dotfile_repo_url', sa.String(512), nullable=True))
        batch_op.add_column(sa.Column('dotfile_branch', sa.String(128), nullable=True, server_default='main'))
        batch_op.add_column(sa.Column('dotfile_enabled', sa.Boolean(), nullable=False, server_default='0'))
