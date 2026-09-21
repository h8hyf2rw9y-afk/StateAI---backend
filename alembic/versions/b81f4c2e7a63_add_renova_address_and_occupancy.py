"""add renova address + occupancy columns

Additive only: five nullable columns on `renova_cases` (street_address,
neighborhood, municipality, postal_code, occupancy_status). Nothing existing
is altered or dropped, and no other table is touched. The new "draft" case
status needs no schema change (statuses are soft enums, plain strings).

Revision ID: b81f4c2e7a63
Revises: a7c3e91d5b20
Create Date: 2026-09-21 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b81f4c2e7a63'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91d5b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLUMNS = ("street_address", "neighborhood", "municipality", "postal_code", "occupancy_status")


def upgrade() -> None:
    """Upgrade schema."""
    for name in NEW_COLUMNS:
        op.add_column('renova_cases', sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for name in reversed(NEW_COLUMNS):
        op.drop_column('renova_cases', name)
