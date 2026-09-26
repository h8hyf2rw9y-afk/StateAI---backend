"""add Renova RenovaCase.archived

Hides a case from the default Leads -> Renova list without deleting it (there
is no delete route by design). Every existing row gets archived=false — no
case is hidden by this migration, someone has to archive it explicitly, and
only rejected/cancelled cases can be (enforced in RenovaCaseService, not the
database).

Revision ID: d4a8e3f61c92
Revises: c9e5f1a72b84
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a8e3f61c92"
down_revision: Union[str, Sequence[str], None] = "c9e5f1a72b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "renova_cases",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("renova_cases", "archived")
