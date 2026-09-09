from __future__ import annotations

import uuid

from sqlalchemy import select

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
        stmt = stmt.order_by(Task.due_at.asc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())
