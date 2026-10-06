"""add Renova post-acceptance operation tracking

Revision ID: f8c1d4e2a907
Revises: f1c2d3e4a5b6
Create Date: 2026-10-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8c1d4e2a907"
down_revision: Union[str, Sequence[str], None] = "f1c2d3e4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("renova_cases", sa.Column("operation_stage", sa.String(), nullable=True))
    op.add_column("renova_cases", sa.Column("operation_next_action", sa.Text(), nullable=True))
    op.add_column("renova_cases", sa.Column("operation_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("renova_cases", sa.Column("operation_stage_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_renova_cases_org_operation_stage",
        "renova_cases",
        ["organization_id", "operation_stage"],
    )

    # Existing successful cases must not disappear from the new map. An
    # accepted case starts at the first stage; an old purchased case starts
    # at the earliest honest post-purchase stage and can be reclassified.
    op.execute(
        sa.text(
            """
            UPDATE renova_cases
            SET operation_stage = CASE
                    WHEN status = 'accepted' THEN 'proposal_accepted'
                    WHEN status = 'purchased' THEN 'renovation'
                END,
                operation_stage_updated_at = updated_at
            WHERE status IN ('accepted', 'purchased')
              AND operation_stage IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_renova_cases_org_operation_stage", table_name="renova_cases")
    op.drop_column("renova_cases", "operation_stage_updated_at")
    op.drop_column("renova_cases", "operation_due_at")
    op.drop_column("renova_cases", "operation_next_action")
    op.drop_column("renova_cases", "operation_stage")
