"""add AI session model for session resumption

Revision ID: a1b2c3d4e5f6
Revises: 443f6eca1717
Create Date: 2025-11-13 17:50:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "443f6eca1717"
branch_labels = None
depends_on = None


def upgrade():
    # Create ai_sessions table
    op.create_table(
        "ai_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=50), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tmux_target", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_sessions_tool"), "ai_sessions", ["tool"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_ai_sessions_tool"), table_name="ai_sessions")
    op.drop_table("ai_sessions")
