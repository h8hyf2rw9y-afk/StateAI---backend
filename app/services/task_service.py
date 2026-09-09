from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.task import Task
from app.repositories.buyer_requirement_repo import BuyerRequirementRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.property_interest_repo import PropertyInterestRepository
from app.repositories.property_repo import PropertyRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.audit_service import AuditService


class TaskService:
    """"Something that needs to happen" — see app/models/task.py for why this is deliberately not an Activity."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = TaskRepository(db)
        self.contact_repo = ContactRepository(db)
        self.property_repo = PropertyRepository(db)
        self.buyer_requirement_repo = BuyerRequirementRepository(db)
        self.property_interest_repo = PropertyInterestRepository(db)
        self.audit = AuditService(db)

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        status_: str | None = None,
        priority: str | None = None,
        assigned_to_user_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        property_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        return self.repo.list(
            organization_id,
            status=status_,
            priority=priority,
            assigned_to_user_id=assigned_to_user_id,
            contact_id=contact_id,
            property_id=property_id,
            limit=limit,
            offset=offset,
        )

    def get_or_404(self, organization_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.repo.get(organization_id, task_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")
        return task

    def _validate_references(self, organization_id: uuid.UUID, data) -> None:
        """Never trusts a client-supplied contact/property/buyer_requirement/property_interest id — each must resolve within this same organization, same pattern as PropertyInterestService.create/ActivityService.create."""
        if data.contact_id is not None and self.contact_repo.get(organization_id, data.contact_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        if data.property_id is not None and self.property_repo.get(organization_id, data.property_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")
        if (
            data.buyer_requirement_id is not None
            and self.buyer_requirement_repo.get(organization_id, data.buyer_requirement_id) is None
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Buyer requirement not found.")
        if (
            data.property_interest_id is not None
            and self.property_interest_repo.get(organization_id, data.property_interest_id) is None
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property interest not found.")

    def create(self, organization_id: uuid.UUID, data: TaskCreate, actor_user_id: uuid.UUID | None) -> Task:
        self._validate_references(organization_id, data)
        task = self.repo.create(organization_id, created_by_user_id=actor_user_id, status="pending", **data.model_dump())
        after = TaskRead.model_validate(task).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="task",
            entity_id=task.id,
            action="TASK_CREATED",
            after=after,
        )
        self.db.commit()
        self.db.refresh(task)
        return task

    def update(
        self, organization_id: uuid.UUID, task_id: uuid.UUID, data: TaskUpdate, actor_user_id: uuid.UUID | None
    ) -> Task:
        task = self.get_or_404(organization_id, task_id)
        self._validate_references(organization_id, data)
        before = TaskRead.model_validate(task).model_dump(mode="json")

        fields = data.model_dump(exclude_unset=True)
        # Completing a task auto-stamps completed_at unless the caller already gave one explicitly.
        if fields.get("status") == "completed" and "completed_at" not in fields and task.completed_at is None:
            fields["completed_at"] = datetime.now(timezone.utc)

        updated = self.repo.update(task, **fields)
        after = TaskRead.model_validate(updated).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="task",
            entity_id=updated.id,
            action="TASK_UPDATED",
            before=before,
            after=after,
        )
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def delete(self, organization_id: uuid.UUID, task_id: uuid.UUID, actor_user_id: uuid.UUID | None) -> None:
        task = self.get_or_404(organization_id, task_id)
        before = TaskRead.model_validate(task).model_dump(mode="json")
        deleted_id = task.id
        self.repo.delete(task)
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="task",
            entity_id=deleted_id,
            action="TASK_DELETED",
            before=before,
        )
        self.db.commit()
