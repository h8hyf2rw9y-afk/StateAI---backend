"""add renova_cases (independent house-flipping evaluation module)

Creates ONE new table. It touches no existing table and has no foreign key to
contacts, contact_roles, buyer_requirements, property_interests, opportunities
or properties — Renova is a separate business model that only shares the Leads
page in the UI (see app/models/renova_case.py). Its only relations are to
`organizations` (isolation) and to `users` (advisor / creator).

`nss_encrypted` and `credit_number_encrypted` store Fernet ciphertext only.

Revision ID: a7c3e91d5b20
Revises: 932767fd7b15
Create Date: 2026-09-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91d5b20'
down_revision: Union[str, Sequence[str], None] = '932767fd7b15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('renova_cases',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('assigned_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('source', sa.String(), server_default='whatsapp', nullable=False),
    sa.Column('status', sa.String(), server_default='new', nullable=False),
    sa.Column('owner_name', sa.String(), nullable=False),
    sa.Column('owner_phone', sa.String(), nullable=False),
    sa.Column('marital_status', sa.String(), nullable=True),
    sa.Column('spouse_name', sa.String(), nullable=True),
    sa.Column('spouse_phone', sa.String(), nullable=True),
    sa.Column('nss_encrypted', sa.Text(), nullable=True),
    sa.Column('credit_number_encrypted', sa.Text(), nullable=True),
    sa.Column('dwelling_type', sa.String(), nullable=True),
    sa.Column('floors', sa.SmallInteger(), nullable=True),
    sa.Column('bathrooms', sa.Numeric(precision=3, scale=1), nullable=True),
    sa.Column('bedrooms', sa.SmallInteger(), nullable=True),
    sa.Column('conditions', sa.Text(), nullable=True),
    sa.Column('has_deeds', sa.String(), server_default='unknown', nullable=False),
    sa.Column('deeds_holder_name', sa.String(), nullable=True),
    sa.Column('currency', sa.String(), server_default='MXN', nullable=False),
    sa.Column('final_offer', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('market_value', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('property_tax_debt', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('other_debt', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('water_debt', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('electricity_debt', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('gas_debt', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('debt_owed_to', sa.String(), nullable=True),
    sa.Column('owner_expected_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('sale_reason', sa.Text(), nullable=True),
    sa.Column('key_questions', sa.Text(), nullable=True),
    sa.Column('general_situation', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('final_offer IS NULL OR final_offer >= 0', name='ck_renova_cases_final_offer_non_negative'),
    sa.CheckConstraint('market_value IS NULL OR market_value >= 0', name='ck_renova_cases_market_value_non_negative'),
    sa.CheckConstraint('property_tax_debt IS NULL OR property_tax_debt >= 0', name='ck_renova_cases_property_tax_debt_non_negative'),
    sa.CheckConstraint('other_debt IS NULL OR other_debt >= 0', name='ck_renova_cases_other_debt_non_negative'),
    sa.CheckConstraint('water_debt IS NULL OR water_debt >= 0', name='ck_renova_cases_water_debt_non_negative'),
    sa.CheckConstraint('electricity_debt IS NULL OR electricity_debt >= 0', name='ck_renova_cases_electricity_debt_non_negative'),
    sa.CheckConstraint('gas_debt IS NULL OR gas_debt >= 0', name='ck_renova_cases_gas_debt_non_negative'),
    sa.CheckConstraint('owner_expected_amount IS NULL OR owner_expected_amount >= 0', name='ck_renova_cases_owner_expected_amount_non_negative'),
    sa.CheckConstraint('floors IS NULL OR floors >= 0', name='ck_renova_cases_floors_non_negative'),
    sa.CheckConstraint('bathrooms IS NULL OR bathrooms >= 0', name='ck_renova_cases_bathrooms_non_negative'),
    sa.CheckConstraint('bedrooms IS NULL OR bedrooms >= 0', name='ck_renova_cases_bedrooms_non_negative'),
    sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_renova_cases_org_assigned_user', 'renova_cases', ['organization_id', 'assigned_user_id'], unique=False)
    op.create_index('ix_renova_cases_org_entry_date', 'renova_cases', ['organization_id', 'entry_date'], unique=False)
    op.create_index('ix_renova_cases_org_status', 'renova_cases', ['organization_id', 'status'], unique=False)
    op.create_index('ix_renova_cases_organization_id', 'renova_cases', ['organization_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_renova_cases_organization_id', table_name='renova_cases')
    op.drop_index('ix_renova_cases_org_status', table_name='renova_cases')
    op.drop_index('ix_renova_cases_org_entry_date', table_name='renova_cases')
    op.drop_index('ix_renova_cases_org_assigned_user', table_name='renova_cases')
    op.drop_table('renova_cases')
