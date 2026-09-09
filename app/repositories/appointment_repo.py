from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.appointment import Appointment
from app.repositories.base import OrgScopedRepository


class AppointmentRepository(OrgScopedRepository[Appointment]):
    model = Appointment

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        contact_id: uuid.UUID | None = None,
        property_id: uuid.UUID | None = None,
        opportunity_id: uuid.UUID | None = None,
        assigned_to_user_id: uuid.UUID | None = None,
        start_from: datetime | None = None,
        start_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Appointment]:
        stmt = select(Appointment).where(Appointment.organization_id == organization_id)
        if status is not None:
            stmt = stmt.where(Appointment.status == status)
        if contact_id is not None:
            stmt = stmt.where(Appointment.contact_id == contact_id)
        if property_id is not None:
            stmt = stmt.where(Appointment.property_id == property_id)
        if opportunity_id is not None:
            stmt = stmt.where(Appointment.opportunity_id == opportunity_id)
        if assigned_to_user_id is not None:
            stmt = stmt.where(Appointment.assigned_to_user_id == assigned_to_user_id)
        if start_from is not None:
            stmt = stmt.where(Appointment.start_at >= start_from)
        if start_to is not None:
            stmt = stmt.where(Appointment.start_at <= start_to)
        stmt = stmt.order_by(Appointment.start_at.asc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())
