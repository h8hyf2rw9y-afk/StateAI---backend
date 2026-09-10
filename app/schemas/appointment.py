import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator

from app.schemas.common import ORMModel
from app.schemas.enums import AppointmentStatus, AppointmentType


class AppointmentBase(BaseModel):
    assigned_to_user_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    start_at: datetime
    end_at: datetime
    location: str | None = None
    appointment_type: AppointmentType
    status: AppointmentStatus = "scheduled"

    @model_validator(mode="after")
    def _start_before_end(self) -> "AppointmentBase":
        if self.start_at > self.end_at:
            raise ValueError("start_at must be before or equal to end_at.")
        return self


class AppointmentCreate(AppointmentBase):
    pass


class AppointmentUpdate(BaseModel):
    """All fields optional — PATCH semantics. Doesn't reuse the start/end validator: a partial update shouldn't have to resend both (the service re-validates the merged row, same pattern as BuyerRequirementUpdate)."""

    assigned_to_user_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    location: str | None = None
    appointment_type: AppointmentType | None = None
    status: AppointmentStatus | None = None
    # Phase 5 — User Story F/K: not a column on Appointment itself (see
    # app/models/appointment.py — unchanged). When provided alongside
    # status="completed" (or the appointment is already completed),
    # AppointmentService.update creates one real Activity from it instead
    # of storing the text a second time here — "the outcome becomes
    # meaningful CRM context" (Activity history, LeadContext, the Follow-up
    # and Pipeline agents) without duplicating it onto this row too. Never
    # itself returned by AppointmentRead — it's an instruction to the
    # service, not a persisted field.
    outcome_notes: str | None = None


class AppointmentRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    assigned_to_user_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    property_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime
    location: str | None
    status: str
    appointment_type: str
    external_calendar_event_id: str | None
    external_calendar_provider: str | None
    created_at: datetime
    updated_at: datetime
