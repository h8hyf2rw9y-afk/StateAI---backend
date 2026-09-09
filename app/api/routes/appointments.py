import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.appointment import AppointmentCreate, AppointmentRead, AppointmentUpdate
from app.schemas.enums import AppointmentStatus
from app.schemas.user import CurrentUser
from app.services.appointment_service import AppointmentService

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("", response_model=list[AppointmentRead])
def list_appointments(
    status_: AppointmentStatus | None = Query(None, alias="status"),
    contact_id: uuid.UUID | None = Query(None),
    property_id: uuid.UUID | None = Query(None),
    assigned_to_user_id: uuid.UUID | None = Query(None),
    start_from: datetime | None = Query(None),
    start_to: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[AppointmentRead]:
    return AppointmentService(db).list(
        current_user.organization_id,
        status=status_,
        contact_id=contact_id,
        property_id=property_id,
        assigned_to_user_id=assigned_to_user_id,
        start_from=start_from,
        start_to=start_to,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
def create_appointment(
    data: AppointmentCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    return AppointmentService(db).create(current_user.organization_id, data, actor_user_id=current_user.id)


@router.get("/{appointment_id}", response_model=AppointmentRead)
def get_appointment(
    appointment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    return AppointmentService(db).get_or_404(current_user.organization_id, appointment_id)


@router.patch("/{appointment_id}", response_model=AppointmentRead)
def update_appointment(
    appointment_id: uuid.UUID,
    data: AppointmentUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> AppointmentRead:
    return AppointmentService(db).update(current_user.organization_id, appointment_id, data, actor_user_id=current_user.id)


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appointment(
    appointment_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    AppointmentService(db).delete(current_user.organization_id, appointment_id, actor_user_id=current_user.id)
