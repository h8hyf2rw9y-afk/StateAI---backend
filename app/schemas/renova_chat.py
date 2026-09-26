import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from app.schemas.common import ORMModel

RenovaChatIntent = Literal[
    "active_count",
    "active_list",
    "pipeline_summary",
    "case_summary",
    "total_debt",
    "debt_breakdown",
    "phone",
    "address",
    "status",
    "entry_date",
    "market_value",
    "final_offer",
    "expected_amount",
    "protected_data",
    "help",
    "unsupported",
]


class ParsedRenovaQuestion(BaseModel):
    """LLM output: intent only. No database record is ever included in its prompt."""

    intent: RenovaChatIntent
    owner_name: str | None = Field(default=None, max_length=200)


class RenovaChatConversationCreate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None


class RenovaChatQuestion(BaseModel):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class RenovaChatConversationRead(ORMModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


class RenovaChatMessageRead(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    intent: str | None
    referenced_case_id: uuid.UUID | None
    created_at: datetime


class RenovaChatTurn(BaseModel):
    conversation: RenovaChatConversationRead
    user_message: RenovaChatMessageRead
    assistant_message: RenovaChatMessageRead
