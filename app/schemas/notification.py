import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.enums import NotificationType


class NotificationCreate(BaseModel):
    """Not exposed via a public POST route — see app/api/routes/notifications.py. Used internally by services that decide a user should be notified about something."""

    user_id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None


class NotificationUpdate(BaseModel):
    """The only client-writable action on a notification: marking it read."""

    read: bool = True


class NotificationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: str
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime
