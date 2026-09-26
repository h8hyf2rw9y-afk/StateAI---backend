"""add Renova property_tax_debt_unit (pesos vs. years)

A WhatsApp conversation sometimes only reveals how many YEARS of property tax
are owed, never the peso amount. Adds property_tax_debt_unit ("mxn"/"years")
so that number can be captured honestly instead of forced into a peso field.
Every existing row gets "mxn" (its property_tax_debt, if any, was already a
peso figure) — no data is reinterpreted or lost.

Revision ID: c9e5f1a72b84
Revises: b2f7a4c9d310
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9e5f1a72b84"
down_revision: Union[str, Sequence[str], None] = "b2f7a4c9d310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "renova_cases",
        sa.Column("property_tax_debt_unit", sa.String(), nullable=False, server_default="mxn"),
    )


def downgrade() -> None:
    op.drop_column("renova_cases", "property_tax_debt_unit")
