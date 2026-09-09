import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.enums import TaskPriority, TaskStatus, TaskType


class TaskBase(BaseModel):
    assigned_to_user_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    buyer_requirement_id: uuid.UUID | None = None
    property_interest_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    task_type: TaskType
    priority: TaskPriority = "medium"
    due_at: datetime


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    """All fields optional — PATCH semantics. Setting status="completed" without an explicit completed_at auto-stamps it server-side — see TaskService.update."""

    assigned_to_user_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    buyer_requirement_id: uuid.UUID | None = None
    property_interest_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    task_type: TaskType | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None


class TaskRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    assigned_to_user_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    property_id: uuid.UUID | None
    buyer_requirement_id: uuid.UUID | None
    property_interest_id: uuid.UUID | None
    title: str
    description: str | None
    task_type: str
    status: str
    priority: str
    due_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
