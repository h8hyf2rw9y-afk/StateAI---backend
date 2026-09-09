import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.enums import ActivityDirection, ActivityType


class ActivityCreate(BaseModel):
    activity_type: ActivityType
    direction: ActivityDirection | None = None
    property_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    occurred_at: datetime
    notes: str


class ActivityRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    contact_id: uuid.UUID
    property_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    activity_type: str
    direction: str | None
    occurred_at: datetime
    notes: str
    created_at: datetime
    updated_at: datetime
