"""Add notifications and notification_preferences tables

Revision ID: 61edecd936aa
Revises: 6ae814198ff4
Create Date: 2025-12-09 17:05:35.496728

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '61edecd936aa'
down_revision = '6ae814198ff4'
branch_labels = None
depends_on = None


def upgrade():
    # Create notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('notification_type', sa.String(64), nullable=False),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('resource_type', sa.String(64), nullable=True),
        sa.Column('resource_id', sa.Integer(), nullable=True),
        sa.Column('resource_url', sa.String(1024), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, default=False),
        sa.Column('priority', sa.String(32), nullable=False, default='normal'),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_notification_type', 'notifications', ['notification_type'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
    op.create_index('idx_notifications_user_unread', 'notifications', ['user_id', 'is_read', 'created_at'])

    # Create notification_preferences table
    op.create_table(
        'notification_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('enabled_types_json', sa.Text(), nullable=False, default='[]'),
        sa.Column('muted_projects_json', sa.Text(), nullable=False, default='[]'),
        sa.Column('muted_integrations_json', sa.Text(), nullable=False, default='[]'),
        sa.Column('email_notifications', sa.Boolean(), nullable=False, default=False),
        sa.Column('email_frequency', sa.String(32), nullable=False, default='realtime'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id'),
    )


def downgrade():
    op.drop_table('notification_preferences')
    op.drop_index('idx_notifications_user_unread', table_name='notifications')
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_notification_type', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
