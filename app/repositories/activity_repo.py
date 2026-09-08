from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.activity import Activity
from app.repositories.base import OrgScopedRepository


class ActivityRepository(OrgScopedRepository[Activity]):
    model = Activity

    def list_for_contact(
        self,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        activity_type: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> list[Activity]:
        stmt = select(Activity).where(
            Activity.organization_id == organization_id, Activity.contact_id == contact_id
        )
        stmt = self._apply_filters(stmt, activity_type, occurred_from, occurred_to)
        stmt = stmt.order_by(Activity.occurred_at.asc())
        return list(self.db.execute(stmt).scalars().all())

    def list_for_property(
        self,
        organization_id: uuid.UUID,
        property_id: uuid.UUID,
        *,
        activity_type: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> list[Activity]:
        stmt = select(Activity).where(
            Activity.organization_id == organization_id, Activity.property_id == property_id
        )
        stmt = self._apply_filters(stmt, activity_type, occurred_from, occurred_to)
        stmt = stmt.order_by(Activity.occurred_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    @staticmethod
    def _apply_filters(stmt, activity_type: str | None, occurred_from: datetime | None, occurred_to: datetime | None):
        if activity_type is not None:
            stmt = stmt.where(Activity.activity_type == activity_type)
        if occurred_from is not None:
            stmt = stmt.where(Activity.occurred_at >= occurred_from)
        if occurred_to is not None:
            stmt = stmt.where(Activity.occurred_at <= occurred_to)
        return stmt
