"""add users.email, users.is_active and users.deactivated_at

Revision ID: f1c2d3e4a5b6
Revises: e6b3a12c4d90
Create Date: 2026-10-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1c2d3e4a5b6"
down_revision: Union[str, Sequence[str], None] = "e6b3a12c4d90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(), nullable=True))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    # Existing teammates: copy their email once from Supabase Auth so the
    # members list can show who is who. New rows get it from the JWT.
    op.execute("UPDATE users SET email = lower(au.email) FROM auth.users AS au WHERE au.id = users.id")


def downgrade() -> None:
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "email")
