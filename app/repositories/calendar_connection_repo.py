from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.calendar_connection import CalendarConnection
from app.repositories.base import OrgScopedRepository


class CalendarConnectionRepository(OrgScopedRepository[CalendarConnection]):
    model = CalendarConnection

    def list_for_user(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[CalendarConnection]:
        stmt = (
            select(CalendarConnection)
            .where(CalendarConnection.organization_id == organization_id, CalendarConnection.user_id == user_id)
            .order_by(CalendarConnection.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
