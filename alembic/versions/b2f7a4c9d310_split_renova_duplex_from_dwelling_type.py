"""split Renova duplex configuration from dwelling_type

`dwelling_type` used to accept "duplex" as a third, mutually-exclusive value
alongside "house"/"apartment" — ambiguous, since a real property can be a
"Casa dúplex" or a "Departamento dúplex" and the old model could not say
which. This adds `is_duplex` (a separate boolean configuration) and migrates
every existing row with dwelling_type="duplex" to is_duplex=true with
dwelling_type=NULL — the base type was never actually known for those rows,
so nothing is invented; the UI shows this as "tipo base por confirmar". Rows
already "house"/"apartment" are untouched (is_duplex defaults to false).

No existing case is dropped or loses data that was actually captured.

Revision ID: b2f7a4c9d310
Revises: 7f3c1a9e42d1
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2f7a4c9d310"
down_revision: Union[str, Sequence[str], None] = "7f3c1a9e42d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_renova_cases = sa.table("renova_cases", sa.column("dwelling_type", sa.String()), sa.column("is_duplex", sa.Boolean()))


def upgrade() -> None:
    op.add_column(
        "renova_cases",
        sa.Column("is_duplex", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        _renova_cases.update()
        .where(_renova_cases.c.dwelling_type == "duplex")
        .values(is_duplex=True, dwelling_type=None)
    )


def downgrade() -> None:
    # Best-effort only: the base type that was NULL because it was never
    # known cannot be un-forgotten. Any case currently is_duplex=true
    # collapses back to the old single "duplex" value regardless of its
    # (possibly since-filled-in) dwelling_type, matching the old model's own
    # limitation.
    op.execute(_renova_cases.update().where(_renova_cases.c.is_duplex.is_(True)).values(dwelling_type="duplex"))
    op.drop_column("renova_cases", "is_duplex")
