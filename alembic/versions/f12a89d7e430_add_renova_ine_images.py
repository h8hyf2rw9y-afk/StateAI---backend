"""Store encrypted INE images on Renova cases.

Revision ID: f12a89d7e430
Revises: b81f4c2e7a63
"""
from alembic import op
import sqlalchemy as sa

revision = 'f12a89d7e430'
down_revision = 'b81f4c2e7a63'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('renova_cases', sa.Column('ine_front_encrypted', sa.Text(), nullable=True))
    op.add_column('renova_cases', sa.Column('ine_back_encrypted', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('renova_cases', 'ine_back_encrypted')
    op.drop_column('renova_cases', 'ine_front_encrypted')
