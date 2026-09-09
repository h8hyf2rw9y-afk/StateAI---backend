import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.enums import CalendarProviderName


class CalendarConnectionCreate(BaseModel):
    """Registers *intent* to connect a provider — there is no OAuth flow behind this yet (see README). No token fields exist anywhere on this schema or the model it backs."""

    provider: CalendarProviderName


class CalendarConnectionRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    provider: str
    external_account_id: str | None
    scopes: str | None
    expires_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime
