import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user, require_role
from app.schemas.activity import ActivityRead
from app.schemas.enums import ActivityType
from app.schemas.property import PropertyCreate, PropertyFeatureAssign, PropertyRead, PropertyUpdate
from app.schemas.user import CurrentUser
from app.services.activity_service import ActivityService
from app.services.property_service import PropertyService

router = APIRouter(prefix="/properties", tags=["properties"])


@router.get("", response_model=list[PropertyRead])
def list_properties(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[PropertyRead]:
    return PropertyService(db).list(current_user.organization_id, limit=limit, offset=offset)


@router.post("", response_model=PropertyRead, status_code=status.HTTP_201_CREATED)
def create_property(
    data: PropertyCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyRead:
    return PropertyService(db).create(current_user.organization_id, data, actor_user_id=current_user.id)


@router.get("/{property_id}", response_model=PropertyRead)
def get_property(
    property_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyRead:
    return PropertyService(db).get_or_404(current_user.organization_id, property_id)


@router.patch("/{property_id}", response_model=PropertyRead)
def update_property(
    property_id: uuid.UUID,
    data: PropertyUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyRead:
    return PropertyService(db).update(current_user.organization_id, property_id, data, actor_user_id=current_user.id)


@router.delete(
    "/{property_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role("owner", "admin"))]
)
def delete_property(
    property_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    PropertyService(db).delete(current_user.organization_id, property_id, actor_user_id=current_user.id)


@router.post("/{property_id}/features", response_model=PropertyRead)
def add_property_feature(
    property_id: uuid.UUID,
    data: PropertyFeatureAssign,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyRead:
    return PropertyService(db).add_feature(current_user.organization_id, property_id, data.feature_key)


@router.delete("/{property_id}/features/{feature_key}", response_model=PropertyRead)
def remove_property_feature(
    property_id: uuid.UUID,
    feature_key: str,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyRead:
    return PropertyService(db).remove_feature(current_user.organization_id, property_id, feature_key)


@router.get("/{property_id}/activities", response_model=list[ActivityRead])
def list_property_activities(
    property_id: uuid.UUID,
    activity_type: ActivityType | None = Query(None),
    occurred_from: datetime | None = Query(None),
    occurred_to: datetime | None = Query(None),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[ActivityRead]:
    return ActivityService(db).list_for_property(
        current_user.organization_id,
        property_id,
        activity_type=activity_type,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
