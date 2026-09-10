import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.activity import ActivityRead
from app.schemas.user import CurrentUser
from app.services.activity_service import ActivityService

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=list[ActivityRead])
def list_recent_activities(
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[ActivityRead]:
    """
    The organization's most recent activity, newest first — added for the
    Dashboard's "Recent activity" feed (CRM Integration Gaps task). Every
    other activity route below is scoped to one contact/property/opportunity;
    this is the one org-wide feed, same precedent as GET /audit-logs.
    """
    return ActivityService(db).list_recent(current_user.organization_id, limit=limit)


@router.get("/{activity_id}", response_model=ActivityRead)
def get_activity(
    activity_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> ActivityRead:
    return ActivityService(db).get_or_404(current_user.organization_id, activity_id)
