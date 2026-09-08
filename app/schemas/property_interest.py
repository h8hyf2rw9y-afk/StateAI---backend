import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.enums import ContactSource, PropertyInterestStatus


class PropertyInterestBase(BaseModel):
    property_id: uuid.UUID
    status: PropertyInterestStatus = "new"
    source: ContactSource | None = None
    notes: str | None = None
    first_contact_at: datetime | None = None
    last_contact_at: datetime | None = None


class PropertyInterestCreate(PropertyInterestBase):
    pass


class PropertyInterestUpdate(BaseModel):
    status: PropertyInterestStatus | None = None
    source: ContactSource | None = None
    notes: str | None = None
    first_contact_at: datetime | None = None
    last_contact_at: datetime | None = None


class PropertyInterestRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    contact_id: uuid.UUID
    property_id: uuid.UUID
    status: str
    source: str | None
    notes: str | None
    first_contact_at: datetime | None
    last_contact_at: datetime | None
    created_at: datetime
    updated_at: datetime
