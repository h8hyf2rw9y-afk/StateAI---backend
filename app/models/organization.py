import uuid

from sqlalchemy import ForeignKey, Index
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

    organization: Mapped["Organization"] = relationship(back_populates="users")

    __table_args__ = (Index("ix_users_organization_id", "organization_id"),)
