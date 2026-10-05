"""add Renova structured proposal model

Adds proposal_type, debt_coverage_amount and owner_cash_offer to
renova_cases. All three are nullable and every existing row gets
proposal_type=NULL — no existing `final_offer` value is read, split or
reinterpreted by this migration. A NULL proposal_type means "this case
predates the structured model (or has no proposal yet)"; RenovaCaseService
never infers debt-vs-cash from the legacy `final_offer` figure, so those
rows stay exactly as ambiguous as they already were until someone
classifies them through the app.

Revision ID: dbec420e1b00
Revises: afb09875036b
Create Date: 2026-10-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dbec420e1b00"
down_revision: Union[str, Sequence[str], None] = "afb09875036b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("renova_cases", sa.Column("proposal_type", sa.String(), nullable=True))
    op.add_column("renova_cases", sa.Column("debt_coverage_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("renova_cases", sa.Column("owner_cash_offer", sa.Numeric(14, 2), nullable=True))
    op.create_check_constraint(
        "ck_renova_cases_debt_coverage_amount_non_negative",
        "renova_cases",
        "debt_coverage_amount IS NULL OR debt_coverage_amount >= 0",
    )
    op.create_check_constraint(
        "ck_renova_cases_owner_cash_offer_non_negative",
        "renova_cases",
        "owner_cash_offer IS NULL OR owner_cash_offer >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_renova_cases_owner_cash_offer_non_negative", "renova_cases", type_="check")
    op.drop_constraint("ck_renova_cases_debt_coverage_amount_non_negative", "renova_cases", type_="check")
    op.drop_column("renova_cases", "owner_cash_offer")
    op.drop_column("renova_cases", "debt_coverage_amount")
    op.drop_column("renova_cases", "proposal_type")
