import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class OrganizationInvitation(Base, UUIDPKMixin, TimestampMixin):
    """
    A link an owner/admin generates to bring a specific person into their
    EXISTING organization (as opposed to every other sign-up, which gets a
    brand-new one — see app/services/onboarding_service.py). There is no
    outbound email here: the org has no email-sending integration yet, so
    the owner shares `/register?invite={token}` themselves (WhatsApp, etc.)
    — the same reasoning Renova's own WhatsApp-sourced intake already
    leans on throughout this app.

    `email` is who the invite was written for, checked against the
    signing-up Supabase account's own verified JWT email at accept time
    (app/services/organization_invitation_service.py) — not just "whoever
    has the link", so a leaked link alone can't be used by someone else.
    """

    __tablename__ = "organization_invitations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(nullable=False)
    # Soft enum (app/schemas/enums.py): the role the invitee gets once
    # accepted. Never "owner" — see the service's own validation.
    role: Mapped[str] = mapped_column(nullable=False, default="agent", server_default="agent")
    token: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="pending", server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("token", name="uq_organization_invitations_token"),
        Index("ix_organization_invitations_organization_id", "organization_id"),
        Index("ix_organization_invitations_token", "token"),
    )
