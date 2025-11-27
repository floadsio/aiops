"""Remove Claude usage tracking columns

Revision ID: f366ffba1cd8
Revises: b28af6ab4c87
Create Date: 2025-11-27 17:15:46.046375

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f366ffba1cd8'
down_revision = 'b28af6ab4c87'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('claude_usage_last_updated')
        batch_op.drop_column('claude_requests_remaining')
        batch_op.drop_column('claude_requests_limit')
        batch_op.drop_column('claude_output_tokens_remaining')
        batch_op.drop_column('claude_output_tokens_limit')
        batch_op.drop_column('claude_input_tokens_remaining')
        batch_op.drop_column('claude_input_tokens_limit')


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('claude_input_tokens_limit', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('claude_input_tokens_remaining', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('claude_output_tokens_limit', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('claude_output_tokens_remaining', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('claude_requests_limit', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('claude_requests_remaining', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('claude_usage_last_updated', sa.DATETIME(), nullable=True))
