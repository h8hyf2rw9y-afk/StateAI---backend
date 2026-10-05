import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class RenovaFollowUpActivity(Base, UUIDPKMixin, TimestampMixin):
    """One internal contact/scheduling event for an independent Renova case."""

    __tablename__ = "renova_follow_up_activities"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    renova_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("renova_cases.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # "call" records something that happened; "follow_up" schedules the next call.
    activity_type: Mapped[str] = mapped_column(nullable=False)
    result: Mapped[str | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("activity_type IN ('call', 'follow_up')", name="ck_renova_follow_up_activity_type"),
        CheckConstraint(
            "(activity_type = 'call' AND result IS NOT NULL) OR "
            "(activity_type = 'follow_up' AND result IS NULL AND attempt_number IS NULL AND next_follow_up_at IS NOT NULL)",
            name="ck_renova_follow_up_shape",
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('no_answer', 'interested', 'callback_requested', 'not_interested', 'other')",
            name="ck_renova_follow_up_result",
        ),
        CheckConstraint("attempt_number IS NULL OR attempt_number >= 1", name="ck_renova_follow_up_attempt_positive"),
        Index("ix_renova_follow_up_org", "organization_id"),
        Index("ix_renova_follow_up_case_occurred", "renova_case_id", "occurred_at"),
        Index("ix_renova_follow_up_next", "organization_id", "next_follow_up_at"),
    )
