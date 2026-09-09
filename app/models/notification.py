import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin


class Notification(Base, UUIDPKMixin, CreatedAtMixin):
    """
    An in-app notification record for one user — "your task is due,"
    "appointment starting soon." This table only ever gets a row written to
    it directly (see app/services/notification_service.py); nothing in this
    codebase yet scans Task.due_at or Appointment.start_at to create these
    automatically — that requires a scheduled job, which doesn't exist here
    (see the README's Notifications Architecture section for what's
    intentionally deferred: the scheduler, and every delivery channel other
    than this in-app record — email/push/SMS/WhatsApp are not implemented).

    CreatedAtMixin, not TimestampMixin: the only mutation a notification
    ever gets is `read_at` being set once, not a general-purpose
    `updated_at`.
    """

    __tablename__ = "notifications"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Soft enum: notification_type (task_due/appointment_upcoming/...).
    type: Mapped[str] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(nullable=False)

    # What this notification is about, e.g. ("task", <task_id>) — freeform
    # like AuditLog.entity_type/entity_id, for the same reason: every future
    # module can point a notification at its own rows without a schema change.
    related_entity_type: Mapped[str | None] = mapped_column(nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_notifications_organization_id", "organization_id"),
        Index("ix_notifications_user_id", "user_id"),
        Index("ix_notifications_user_read_at", "user_id", "read_at"),
    )
