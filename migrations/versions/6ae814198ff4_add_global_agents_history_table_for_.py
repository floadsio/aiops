"""Add global_agents_history table for versioning

Revision ID: 6ae814198ff4
Revises: 96d3809d2a2a
Create Date: 2025-12-04 20:29:42.319197

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '6ae814198ff4'
down_revision = '96d3809d2a2a'
branch_labels = None
depends_on = None


def upgrade():
    # Create global_agents_history table
    op.create_table(
        'global_agents_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('change_description', sa.String(length=500), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_number')
    )
    op.create_index(
        op.f('ix_global_agents_history_version_number'),
        'global_agents_history',
        ['version_number'],
        unique=True
    )

    # Create initial version from existing global_agent_context if it exists
    conn = op.get_bind()

    # Check if global_agent_context table exists and has content
    global_context_result = conn.execute(
        sa.text("SELECT content FROM global_agent_context LIMIT 1")
    ).fetchone()

    if global_context_result and global_context_result[0]:
        # Create version 1 from existing content
        history_table = table(
            'global_agents_history',
            column('version_number', sa.Integer),
            column('content', sa.Text),
            column('change_description', sa.String),
            column('created_by_user_id', sa.Integer),
            column('created_at', sa.DateTime),
            column('updated_at', sa.DateTime)
        )

        op.bulk_insert(
            history_table,
            [{
                'version_number': 1,
                'content': global_context_result[0],
                'change_description': 'Initial version from migration',
                'created_by_user_id': None,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }]
        )


def downgrade():
    op.drop_index(op.f('ix_global_agents_history_version_number'), table_name='global_agents_history')
    op.drop_table('global_agents_history')
