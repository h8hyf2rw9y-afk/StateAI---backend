import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Task(Base, UUIDPKMixin, TimestampMixin):
    """
    "Something that needs to happen" — a follow-up call, a document
    deadline, a notary appointment reminder, an AI-suggested action a human
    turned into concrete work. Deliberately distinct from Activity, which
    records "something that already happened": a completed Task does not
    become an Activity automatically (a human decides whether the outcome
    is worth logging as one) — merging the two concepts was an explicit
    non-goal for this module.
    """

    __tablename__ = "tasks"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL: an unassigned task is still a valid, visible backlog item —
    # deleting the assignee's user account shouldn't delete the task itself.
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # All four optional and CASCADE: a task is meaningful only in relation to
    # whichever of these it's actually about, and stops being actionable
    # once that thing is gone (unlike Activity's historical record, a Task
    # is forward-looking — see the module docstring above).
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=True
    )
    buyer_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("buyer_requirements.id", ondelete="CASCADE"), nullable=True
    )
    property_interest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("property_interests.id", ondelete="CASCADE"), nullable=True
    )

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)

    # Soft enums (app/schemas/enums.py): task_type, status, priority.
    task_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(nullable=False, default="medium")

    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_tasks_organization_id", "organization_id"),
        Index("ix_tasks_contact_id", "contact_id"),
        Index("ix_tasks_property_id", "property_id"),
        Index("ix_tasks_buyer_requirement_id", "buyer_requirement_id"),
        Index("ix_tasks_property_interest_id", "property_interest_id"),
        Index("ix_tasks_assigned_to_user_id", "assigned_to_user_id"),
        Index("ix_tasks_org_status_due", "organization_id", "status", "due_at"),
    )
