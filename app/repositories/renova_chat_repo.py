import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.renova_chat import RenovaChatConversation, RenovaChatMessage


class RenovaChatRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_conversations(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, *, limit: int = 50
    ) -> list[RenovaChatConversation]:
        stmt = (
            select(RenovaChatConversation)
            .where(
                RenovaChatConversation.organization_id == organization_id,
                RenovaChatConversation.user_id == user_id,
            )
            .order_by(RenovaChatConversation.last_message_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_conversation(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> RenovaChatConversation | None:
        stmt = select(RenovaChatConversation).where(
            RenovaChatConversation.id == conversation_id,
            RenovaChatConversation.organization_id == organization_id,
            RenovaChatConversation.user_id == user_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create_conversation(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, title: str
    ) -> RenovaChatConversation:
        conversation = RenovaChatConversation(
            organization_id=organization_id, user_id=user_id, title=title
        )
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def count_recent_user_messages(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, *, seconds: int = 60
    ) -> int:
        since = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        stmt = (
            select(func.count())
            .select_from(RenovaChatMessage)
            .join(
                RenovaChatConversation,
                RenovaChatConversation.id == RenovaChatMessage.conversation_id,
            )
            .where(
                RenovaChatConversation.organization_id == organization_id,
                RenovaChatConversation.user_id == user_id,
                RenovaChatMessage.role == "user",
                RenovaChatMessage.created_at >= since,
            )
        )
        return int(self.db.scalar(stmt) or 0)

    def list_messages(self, conversation_id: uuid.UUID) -> list[RenovaChatMessage]:
        stmt = (
            select(RenovaChatMessage)
            .where(RenovaChatMessage.conversation_id == conversation_id)
            .order_by(RenovaChatMessage.sequence.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_message(
        self,
        conversation_id: uuid.UUID,
        *,
        role: str,
        content: str,
        intent: str | None = None,
        referenced_case_id: uuid.UUID | None = None,
    ) -> RenovaChatMessage:
        next_sequence = (self.db.scalar(
            select(func.max(RenovaChatMessage.sequence)).where(
                RenovaChatMessage.conversation_id == conversation_id
            )
        ) or 0) + 1
        message = RenovaChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sequence=next_sequence,
            intent=intent,
            referenced_case_id=referenced_case_id,
        )
        self.db.add(message)
        self.db.flush()
        return message

    def touch(self, conversation: RenovaChatConversation) -> None:
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.flush()
