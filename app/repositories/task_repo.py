from __future__ import annotations

import uuid

from sqlalchemy import or_, select

from app.models.task import Task
from app.repositories.base import OrgScopedRepository


class TaskRepository(OrgScopedRepository[Task]):
    model = Task

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        priority: str | None = None,
        assigned_to_user_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        property_id: uuid.UUID | None = None,
        opportunity_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        stmt = select(Task).where(Task.organization_id == organization_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if priority is not None:
            stmt = stmt.where(Task.priority == priority)
        if assigned_to_user_id is not None:
            stmt = stmt.where(Task.assigned_to_user_id == assigned_to_user_id)
        if contact_id is not None:
            stmt = stmt.where(Task.contact_id == contact_id)
        if property_id is not None:
            stmt = stmt.where(Task.property_id == property_id)
        if opportunity_id is not None:
            stmt = stmt.where(Task.opportunity_id == opportunity_id)
        stmt = stmt.order_by(Task.due_at.asc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def list_for_contact(
        self,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        opportunity_ids: list[uuid.UUID] | None = None,
        limit: int = 50,
    ) -> list[Task]:
        """
        Used by LeadContextService (app/services/lead_context_service.py) —
        a task about this contact's opportunity doesn't necessarily have its
        own contact_id set (the two fields are independent), so this matches
        either: Task.contact_id == contact_id OR Task.opportunity_id in
        opportunity_ids. Plain contact_id-only filtering (the existing
        list() method above) would silently miss that second case.
        """
        conditions = [Task.contact_id == contact_id]
        if opportunity_ids:
            conditions.append(Task.opportunity_id.in_(opportunity_ids))
        stmt = (
            select(Task)
            .where(Task.organization_id == organization_id, or_(*conditions))
            .order_by(Task.due_at.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())
