import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPKMixin


class Contact(Base, UUIDPKMixin, TimestampMixin):
    """
    The central entity: a real person interacting with the agency. NOT the
    same thing as a "lead" — a Contact accumulates roles, buyer
    requirements, and property interests over time rather than being
    recreated for each new interaction. See the plan's Case A/Case B note.
    """

    __tablename__ = "contacts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str | None] = mapped_column(nullable=True)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    # Soft enums (see app/schemas/enums.py) — plain strings, validated at the API layer only.
    preferred_contact_method: Mapped[str | None] = mapped_column(nullable=True)
    source: Mapped[str | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)

    roles: Mapped[list["ContactRole"]] = relationship(back_populates="contact", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="ck_contacts_email_or_phone"),
        Index("ix_contacts_organization_id", "organization_id"),
        Index("ix_contacts_org_email", "organization_id", "email"),
        Index("ix_contacts_org_phone", "organization_id", "phone"),
    )


class Role(Base):
    """Catalog of contact roles (buyer, seller, owner, ...) — extend by inserting a row, no migration needed."""

    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)


class ContactRole(Base, UUIDPKMixin, CreatedAtMixin):
    """A person may hold multiple roles at once (e.g. buyer + investor) — see the plan's contact_roles note."""

    __tablename__ = "contact_roles"

    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    role_key: Mapped[str] = mapped_column(ForeignKey("roles.key"), nullable=False)

    contact: Mapped["Contact"] = relationship(back_populates="roles")
    role: Mapped["Role"] = relationship()

    __table_args__ = (UniqueConstraint("contact_id", "role_key", name="uq_contact_roles_contact_role"),)
