from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.calendar_connection import CalendarConnection
from app.repositories.calendar_connection_repo import CalendarConnectionRepository
from app.schemas.calendar_connection import CalendarConnectionCreate


class CalendarConnectionService:
    """
    Registers a user's *intent* to sync with an external calendar — no
    OAuth flow exists yet (see app/integrations/calendar/ and the README's
    Calendar Integration Architecture section), so a connection never
    actually reaches status="connected" through this service today.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = CalendarConnectionRepository(db)

    def list_for_user(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[CalendarConnection]:
        return self.repo.list_for_user(organization_id, user_id)

    def get_or_404_for_user(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, connection_id: uuid.UUID
    ) -> CalendarConnection:
        """Org-scoped AND owned by this user — a connection is personal, like a Notification; another org member must not read or delete someone else's."""
        connection = self.repo.get(organization_id, connection_id)
        if connection is None or connection.user_id != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Calendar connection not found.")
        return connection

    def create(self, organization_id: uuid.UUID, user_id: uuid.UUID, data: CalendarConnectionCreate) -> CalendarConnection:
        existing = next(
            (c for c in self.repo.list_for_user(organization_id, user_id) if c.provider == data.provider), None
        )
        if existing is not None:
            return existing
        connection = self.repo.create(organization_id, user_id=user_id, provider=data.provider, status="pending")
        self.db.commit()
        self.db.refresh(connection)
        return connection

    def delete(self, organization_id: uuid.UUID, user_id: uuid.UUID, connection_id: uuid.UUID) -> None:
        connection = self.get_or_404_for_user(organization_id, user_id, connection_id)
        self.repo.delete(connection)
        self.db.commit()
