import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class PropertyInterest(Base, UUIDPKMixin, TimestampMixin):
    """
    "This Contact is interested in THIS Property" — Case A in the plan
    (arrived through a listing), as opposed to BuyerRequirement (Case B,
    arrived looking for criteria). Not unique on (contact_id, property_id):
    a contact can lose and regain interest in the same property over time,
    and that history is worth keeping.
    """

    __tablename__ = "property_interests"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )

    # Soft enums (app/schemas/enums.py): status, source.
    status: Mapped[str] = mapped_column(nullable=False, default="new")
    source: Mapped[str | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)

    first_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_property_interests_organization_id", "organization_id"),
        Index("ix_property_interests_contact_id", "contact_id"),
        Index("ix_property_interests_property_id", "property_id"),
        Index("ix_property_interests_status", "status"),
        Index("ix_property_interests_contact_property", "contact_id", "property_id"),
    )
