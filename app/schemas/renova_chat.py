import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from app.schemas.common import ORMModel

RenovaChatIntent = Literal[
    "active_count",
    "active_list",
    "archived_count",
    "archived_list",
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
    # Read V2 (see app/renova_chat/fields.py): one named case, one
    # allow-listed field. Covers every case-level fact NOT already covered
    # by one of the fixed intents above -- those keep their own intent name
    # for backward compatibility (existing conversation history, existing
    # prompt phrasing) even though, internally, they resolve through the
    # exact same field-resolver dict `case_field` uses.
    "case_field",
    # Read V2 (see app/renova_chat/filters.py): zero or more matching
    # cases, filtered by exactly one allow-listed field/operator/value.
    "filtered_count",
    "filtered_list",
    "protected_data",
    "help",
    "unsupported",
]

# Every case-level fact the chat may answer about ONE named owner/case,
# through the single `case_field` mechanism (app/renova_chat/fields.py).
# This is a CLOSED list: the LLM can only ever select one of these exact
# strings, never an arbitrary column name -- see RENOVA_CASE_FIELD_RESOLVERS
# for what each one actually reads, and app/services/renova_extraction.py
# for the fields that are excluded from every LLM-facing mechanism, this one
# included (NSS, credit number, INE, both phone numbers).
RenovaReadableField = Literal[
    # Already their own intent (kept for backward compatibility); case_field
    # can also name them directly.
    "phone",
    "address",
    "status",
    "entry_date",
    "market_value",
    "final_offer",
    "expected_amount",
    # New in Read V2.
    "dwelling_type",
    "is_duplex",
    "occupancy_status",
    "floors",
    "bathrooms",
    "bedrooms",
    "conditions",
    "has_deeds",
    "deeds_holder_name",
    "sale_reason",
    "general_situation",
    "notes",
    "marital_status",
    "spouse_name",
    "source",
    "property_tax_debt",
    "water_debt",
    "electricity_debt",
    "gas_debt",
    "other_debt",
]

# One allow-listed cross-case filter (app/renova_chat/filters.py). Deliberately
# a single field/operator/value triple, not an arbitrary predicate tree --
# every example this phase needs to support ("negociando", "en Apodaca",
# "dúplex", "sin escrituras", "con adeudo de agua") is one condition.
RenovaFilterField = Literal[
    "status",
    "municipality",
    "is_duplex",
    "has_deeds",
    "has_property_tax_debt",
    "has_water_debt",
    "has_electricity_debt",
    "has_gas_debt",
    "has_other_debt",
]
RenovaFilterOperator = Literal["equals", "is_true", "is_false", "exists"]


class RenovaCaseFilter(BaseModel):
    """
    One condition. Both `field` and `operator` are closed Literals, so the
    model can never request an arbitrary column or a raw SQL fragment --
    only app/renova_chat/filters.py decides which field/operator/value
    combinations are actually valid (e.g. "is_duplex" never takes "equals").
    """

    field: RenovaFilterField
    operator: RenovaFilterOperator
    value: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class ParsedRenovaQuestion(BaseModel):
    """LLM output: intent plus the minimum structured data needed to resolve it. No database record is ever included in its prompt."""

    intent: RenovaChatIntent
    owner_name: str | None = Field(default=None, max_length=200)
    # Only set (and only consulted) when intent == "case_field".
    field: RenovaReadableField | None = None
    # Only set (and only consulted) when intent is "filtered_count" or "filtered_list".
    filter: RenovaCaseFilter | None = None


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
