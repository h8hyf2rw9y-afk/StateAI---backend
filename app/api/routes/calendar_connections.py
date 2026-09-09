import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.calendar_connection import CalendarConnectionCreate, CalendarConnectionRead
from app.schemas.user import CurrentUser
from app.services.calendar_connection_service import CalendarConnectionService

router = APIRouter(prefix="/calendar-connections", tags=["calendar-connections"])


@router.get("", response_model=list[CalendarConnectionRead])
def list_my_calendar_connections(
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[CalendarConnectionRead]:
    """A user's own connections only — see NotificationService for the same "personal, not just org-scoped" reasoning."""
    return CalendarConnectionService(db).list_for_user(current_user.organization_id, current_user.id)


@router.post("", response_model=CalendarConnectionRead, status_code=status.HTTP_201_CREATED)
def create_calendar_connection(
    data: CalendarConnectionCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> CalendarConnectionRead:
    """
    Registers intent to connect a provider. Does NOT perform an OAuth flow —
    there is none yet (see app/integrations/calendar/ and the README). The
    connection's `status` stays "pending" until real OAuth exists.
    """
    return CalendarConnectionService(db).create(current_user.organization_id, current_user.id, data)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_connection(
    connection_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    CalendarConnectionService(db).delete(current_user.organization_id, current_user.id, connection_id)
