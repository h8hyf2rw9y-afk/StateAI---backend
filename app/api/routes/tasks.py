import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.enums import TaskPriority, TaskStatus
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.schemas.user import CurrentUser
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def list_tasks(
    status_: TaskStatus | None = Query(None, alias="status"),
    priority: TaskPriority | None = Query(None),
    assigned_to_user_id: uuid.UUID | None = Query(None),
    contact_id: uuid.UUID | None = Query(None),
    property_id: uuid.UUID | None = Query(None),
    opportunity_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[TaskRead]:
    return TaskService(db).list(
        current_user.organization_id,
        status_=status_,
        priority=priority,
        assigned_to_user_id=assigned_to_user_id,
        contact_id=contact_id,
        property_id=property_id,
        opportunity_id=opportunity_id,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    data: TaskCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> TaskRead:
    return TaskService(db).create(current_user.organization_id, data, actor_user_id=current_user.id)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> TaskRead:
    return TaskService(db).get_or_404(current_user.organization_id, task_id)


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: uuid.UUID,
    data: TaskUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> TaskRead:
    """Setting status="completed" auto-stamps completed_at server-side if not given explicitly — see TaskService.update."""
    return TaskService(db).update(current_user.organization_id, task_id, data, actor_user_id=current_user.id)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    TaskService(db).delete(current_user.organization_id, task_id, actor_user_id=current_user.id)
