"""add AI execution single-flight and idempotency

Revision ID: 7f3c1a9e42d1
Revises: f12a89d7e430
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f3c1a9e42d1"
down_revision: Union[str, Sequence[str], None] = "f12a89d7e430"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_executions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_executions", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.create_index(
        "uq_agent_executions_active",
        "agent_executions",
        ["organization_id", "contact_id", "agent_name"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "uq_agent_executions_org_idempotency_key",
        "agent_executions",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_executions_org_idempotency_key", table_name="agent_executions")
    op.drop_index("uq_agent_executions_active", table_name="agent_executions")
    op.drop_column("agent_executions", "idempotency_key")
    op.drop_column("agent_executions", "completed_at")
