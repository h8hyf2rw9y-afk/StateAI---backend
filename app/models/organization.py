import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Organization(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base, TimestampMixin):
    """
    The bridge between Supabase Auth and the rest of this schema. `id` is
    NOT generated here — it's always the same value as the corresponding
    `auth.users.id` row that Supabase Auth already created when the person
    signed up (via the frontend). Every authenticated request resolves to
    exactly one row here, which is how we know which organization it
    belongs to (see app/core/security.py).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Mirrors the UserRole union in the frontend's types/user.ts.
    role: Mapped[str] = mapped_column(nullable=False, default="agent")
    # A copy of the Supabase Auth email, taken from the verified JWT when the
    # row is created (onboarding / accepting an invitation), so an owner can
    # tell their teammates apart — auth.users itself is never queried at runtime.
    email: Mapped[str | None] = mapped_column(nullable=True)
    # Deactivating keeps the row (and every case it owns) but makes
    # get_current_org_user refuse the account — see app/core/security.py.
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=true())
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="users")

    __table_args__ = (Index("ix_users_organization_id", "organization_id"),)
