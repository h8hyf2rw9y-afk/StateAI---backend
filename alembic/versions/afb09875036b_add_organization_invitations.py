"""add organization invitations

Lets an owner/admin bring a specific person into their EXISTING
organization via a shareable `/register?invite={token}` link, instead of
every sign-up always getting its own brand-new one (see
app/services/onboarding_service.py). No outbound email: the org has no
email-sending integration, so the link itself is shared however the owner
likes (WhatsApp, etc.) — see app/models/organization_invitation.py.

Revision ID: afb09875036b
Revises: d4f7a9c21b31
Create Date: 2026-10-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "afb09875036b"
down_revision: Union[str, Sequence[str], None] = "d4f7a9c21b31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), server_default="agent", nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_organization_invitations_token"),
    )
    op.create_index(
        "ix_organization_invitations_organization_id", "organization_invitations", ["organization_id"]
    )
    op.create_index("ix_organization_invitations_token", "organization_invitations", ["token"])


def downgrade() -> None:
    op.drop_index("ix_organization_invitations_token", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_organization_id", table_name="organization_invitations")
    op.drop_table("organization_invitations")
