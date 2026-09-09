import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.notification import NotificationRead, NotificationUpdate
from app.schemas.user import CurrentUser
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])

# No POST route here on purpose — see app/services/notification_service.py:
# a notification is something this backend's own services decide to create
# for a user, never something an API client fabricates for anyone (including
# themselves) via a public endpoint.


@router.get("", response_model=list[NotificationRead])
def list_my_notifications(
    unread: bool = Query(False, description="Set unread=true to return only unread notifications."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[NotificationRead]:
    """A user's own notifications only — never another org member's, even an owner/admin's."""
    return NotificationService(db).list_for_user(
        current_user.organization_id, current_user.id, unread_only=unread, limit=limit, offset=offset
    )


@router.patch("/{notification_id}", response_model=NotificationRead)
def update_notification(
    notification_id: uuid.UUID,
    data: NotificationUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> NotificationRead:
    """The only supported update: marking read/unread."""
    return NotificationService(db).mark_read(
        current_user.organization_id, current_user.id, notification_id, read=data.read
    )
