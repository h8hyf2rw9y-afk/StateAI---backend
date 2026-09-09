import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Activity(Base, UUIDPKMixin, TimestampMixin):
    """
    A structured record of something that already happened with a Contact —
    a call, a WhatsApp exchange, a viewing, an offer, ... — as opposed to a
    future scheduled event (a separate Appointments module's concern, not
    this one). This is what replaces free-text `notes` as the CRM's actual
    timeline, and what future AI agents (Lead Intelligence, Follow-up,
    Sales Copilot) will read for context.

    `occurred_at` is the business timestamp — *when the thing happened* —
    distinct from the inherited `created_at`/`updated_at` audit trail
    (*when this row was logged*), the same split PropertyInterest already
    uses via `first_contact_at`/`last_contact_at`.
    """

    __tablename__ = "activities"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    # A call/note about a contact in general has no property; "Carlos viewed
    # Casa Cumbres" does. SET NULL (not CASCADE): deleting a property
    # shouldn't erase the historical fact that a call/viewing happened.
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"), nullable=True
    )
    # SET NULL, not CASCADE: an Opportunity is business history that's
    # never hard-deleted in normal use (see app/models/opportunity.py), but
    # if it ever is, the activities that happened along the way remain real
    # historical fact — same reasoning as property_id above.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Soft enums (app/schemas/enums.py): activity_type, direction.
    activity_type: Mapped[str] = mapped_column(nullable=False)
    direction: Mapped[str | None] = mapped_column(nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str] = mapped_column(nullable=False)

    __table_args__ = (
        Index("ix_activities_organization_id", "organization_id"),
        Index("ix_activities_contact_id", "contact_id"),
        Index("ix_activities_property_id", "property_id"),
        Index("ix_activities_opportunity_id", "opportunity_id"),
        Index("ix_activities_activity_type", "activity_type"),
        Index("ix_activities_occurred_at", "occurred_at"),
        Index("ix_activities_contact_occurred", "contact_id", "occurred_at"),
    )
