import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPKMixin


class RenovaChatConversation(Base, UUIDPKMixin, TimestampMixin):
    """A private, user-owned conversation about the organization's Renova cases."""

    __tablename__ = "renova_chat_conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(nullable=False)
    context_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("renova_cases.id", ondelete="SET NULL"), nullable=True
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list["RenovaChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_renova_chat_conversations_org_user_last", "organization_id", "user_id", "last_message_at"),
    )


class RenovaChatMessage(Base, UUIDPKMixin, CreatedAtMixin):
    """One persisted user/assistant turn. Content never contains protected Renova identifiers."""

    __tablename__ = "renova_chat_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("renova_chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    intent: Mapped[str | None] = mapped_column(nullable=True)
    referenced_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("renova_cases.id", ondelete="SET NULL"), nullable=True
    )

    conversation: Mapped[RenovaChatConversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_renova_chat_messages_conversation_created", "conversation_id", "created_at"),
        UniqueConstraint("conversation_id", "sequence", name="uq_renova_chat_messages_conversation_sequence"),
    )
