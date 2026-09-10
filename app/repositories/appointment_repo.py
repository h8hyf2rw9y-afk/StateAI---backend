from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, select

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

    def list_for_contact(
        self,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        opportunity_ids: list[uuid.UUID] | None = None,
        limit: int = 50,
    ) -> list[Appointment]:
        """Used by LeadContextService — see TaskRepository.list_for_contact's docstring for why contact_id-only filtering isn't enough."""
        conditions = [Appointment.contact_id == contact_id]
        if opportunity_ids:
            conditions.append(Appointment.opportunity_id.in_(opportunity_ids))
        stmt = (
            select(Appointment)
            .where(Appointment.organization_id == organization_id, or_(*conditions))
            .order_by(Appointment.start_at.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_upcoming(self, organization_id: uuid.UUID, *, now: datetime, within: timedelta) -> list[Appointment]:
        """
        Used by app/automation/detectors.py's detect_upcoming_appointments.
        `now` is always passed in explicitly (never computed here) so the
        whole detection path is testable with a controlled clock. Only
        "scheduled"/"confirmed" — a cancelled or already-completed
        appointment isn't something to remind anyone about.
        """
        stmt = select(Appointment).where(
            Appointment.organization_id == organization_id,
            Appointment.status.in_(("scheduled", "confirmed")),
            Appointment.start_at >= now,
            Appointment.start_at <= now + within,
        )
        return list(self.db.execute(stmt).scalars().all())
