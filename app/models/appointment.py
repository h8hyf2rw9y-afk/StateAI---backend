import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Appointment(Base, UUIDPKMixin, TimestampMixin):
    """
    A scheduled/planned event — "this showing is booked for Tuesday at 4pm"
    — as opposed to Activity, which records what actually happened. An
    Appointment does not become an Activity automatically once it occurs;
    a human logs the outcome as an Activity separately (see the project's
    intended flow: create appointment -> occurs -> Activity records outcome).

    `external_calendar_event_id`/`external_calendar_provider` are where a
    future two-way sync with Google/Apple/Notion would record "this is
    already mirrored externally as event X" — populated by nothing yet (see
    app/integrations/calendar/ and app/models/calendar_connection.py). This
    PropPilot row is always the source of truth; an external calendar is a
    sync target, never the other way around.
    """

    __tablename__ = "appointments"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # CASCADE for contact_id (mirrors PropertyInterest/BuyerRequirement — a
    # contact-scoped thing stops existing when the contact does). SET NULL
    # for property_id (mirrors Activity.property_id's exact reasoning:
    # deleting a property must not erase the historical fact that an
    # appointment happened/was scheduled there).
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"), nullable=True
    )
    # SET NULL — same reasoning as property_id above and Task.opportunity_id:
    # an Opportunity is business history that's never hard-deleted in normal
    # use, but a scheduled/completed appointment should stay a real record
    # even in the rare case its linked opportunity is gone.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(nullable=True)

    # Soft enums (app/schemas/enums.py): status, appointment_type.
    status: Mapped[str] = mapped_column(nullable=False, default="scheduled")
    appointment_type: Mapped[str] = mapped_column(nullable=False)

    # Soft enum: calendar_provider_name (google/apple/notion). Both columns
    # are NULL until a real sync exists — see the module docstring above.
    external_calendar_event_id: Mapped[str | None] = mapped_column(nullable=True)
    external_calendar_provider: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("start_at <= end_at", name="ck_appointments_start_before_end"),
        Index("ix_appointments_organization_id", "organization_id"),
        Index("ix_appointments_contact_id", "contact_id"),
        Index("ix_appointments_property_id", "property_id"),
        Index("ix_appointments_opportunity_id", "opportunity_id"),
        Index("ix_appointments_assigned_to_user_id", "assigned_to_user_id"),
        Index("ix_appointments_org_start_at", "organization_id", "start_at"),
        Index("ix_appointments_status", "status"),
    )
