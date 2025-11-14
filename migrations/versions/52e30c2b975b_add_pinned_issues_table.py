"""Add pinned issues table

Revision ID: 52e30c2b975b
Revises: ecfad9170dec
Create Date: 2025-11-14 20:51:28.653007

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "52e30c2b975b"
down_revision = "ecfad9170dec"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pinned_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("pinned_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["issue_id"], ["external_issues.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "issue_id", name="uq_user_issue"),
    )
    op.create_index(
        op.f("ix_pinned_issues_user_id"), "pinned_issues", ["user_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_pinned_issues_user_id"), table_name="pinned_issues")
    op.drop_table("pinned_issues")
