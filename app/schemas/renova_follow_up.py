import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel

RenovaFollowUpActivityType = Literal["call", "follow_up"]
RenovaCallResult = Literal["no_answer", "interested", "callback_requested", "not_interested", "other"]


class RenovaFollowUpActivityCreate(BaseModel):
    activity_type: RenovaFollowUpActivityType
    result: RenovaCallResult | None = None
    occurred_at: datetime
    next_follow_up_at: datetime | None = None
    attempt_number: int | None = Field(None, ge=1, le=999)
    notes: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.activity_type == "call" and self.result is None:
            raise ValueError("result is required for a call.")
        if self.activity_type == "follow_up":
            if self.next_follow_up_at is None:
                raise ValueError("next_follow_up_at is required for a follow-up.")
            if self.result is not None or self.attempt_number is not None:
                raise ValueError("A scheduled follow-up cannot carry a call result or attempt number.")
        return self


class RenovaFollowUpActivityUpdate(BaseModel):
    result: RenovaCallResult | None = None
    occurred_at: datetime | None = None
    next_follow_up_at: datetime | None = None
    attempt_number: int | None = Field(None, ge=1, le=999)
    notes: str | None = Field(None, max_length=2000)


class RenovaFollowUpActivityRead(ORMModel):
    id: uuid.UUID
    renova_case_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    activity_type: str
    result: str | None
    occurred_at: datetime
    next_follow_up_at: datetime | None
    attempt_number: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class RenovaFollowUpSummary(BaseModel):
    last_call_activity_id: uuid.UUID | None = None
    last_call_at: datetime | None = None
    last_result: str | None = None
    contact_attempt_count: int = 0
    next_follow_up_at: datetime | None = None
    is_follow_up_overdue: bool = False
    contact_state: str = "never_contacted"
    note_preview: str | None = None


class RenovaFollowUpDetail(BaseModel):
    summary: RenovaFollowUpSummary
    activities: list[RenovaFollowUpActivityRead]
