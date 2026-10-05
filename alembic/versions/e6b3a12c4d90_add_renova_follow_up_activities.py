"""add Renova follow-up activities

Revision ID: e6b3a12c4d90
Revises: dbec420e1b00
Create Date: 2026-10-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6b3a12c4d90"
down_revision: Union[str, Sequence[str], None] = "dbec420e1b00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "renova_follow_up_activities",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("renova_case_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("activity_type", sa.String(), nullable=False),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("activity_type IN ('call', 'follow_up')", name="ck_renova_follow_up_activity_type"),
        sa.CheckConstraint(
            "(activity_type = 'call' AND result IS NOT NULL) OR "
            "(activity_type = 'follow_up' AND result IS NULL AND attempt_number IS NULL AND next_follow_up_at IS NOT NULL)",
            name="ck_renova_follow_up_shape",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('no_answer', 'interested', 'callback_requested', 'not_interested', 'other')",
            name="ck_renova_follow_up_result",
        ),
        sa.CheckConstraint("attempt_number IS NULL OR attempt_number >= 1", name="ck_renova_follow_up_attempt_positive"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["renova_case_id"], ["renova_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_renova_follow_up_org", "renova_follow_up_activities", ["organization_id"])
    op.create_index(
        "ix_renova_follow_up_case_occurred",
        "renova_follow_up_activities",
        ["renova_case_id", "occurred_at"],
    )
    op.create_index(
        "ix_renova_follow_up_next",
        "renova_follow_up_activities",
        ["organization_id", "next_follow_up_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_renova_follow_up_next", table_name="renova_follow_up_activities")
    op.drop_index("ix_renova_follow_up_case_occurred", table_name="renova_follow_up_activities")
    op.drop_index("ix_renova_follow_up_org", table_name="renova_follow_up_activities")
    op.drop_table("renova_follow_up_activities")
