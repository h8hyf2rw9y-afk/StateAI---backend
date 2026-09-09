import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user, require_role
from app.schemas.activity import ActivityCreate, ActivityRead
from app.schemas.buyer_requirement import BuyerRequirementCreate, BuyerRequirementRead
from app.schemas.contact import ContactCreate, ContactRead, ContactRoleAssign, ContactUpdate
from app.schemas.enums import ActivityType
from app.schemas.property_interest import PropertyInterestCreate, PropertyInterestRead
from app.schemas.user import CurrentUser
from app.services.activity_service import ActivityService
from app.services.buyer_requirement_service import BuyerRequirementService
from app.services.contact_service import ContactService
from app.services.property_interest_service import PropertyInterestService

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactRead])
def list_contacts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[ContactRead]:
    return ContactService(db).list(current_user.organization_id, limit=limit, offset=offset)


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact(
    data: ContactCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> ContactRead:
    return ContactService(db).create(current_user.organization_id, data, actor_user_id=current_user.id)


@router.get("/{contact_id}", response_model=ContactRead)
def get_contact(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> ContactRead:
    return ContactService(db).get_or_404(current_user.organization_id, contact_id)


@router.patch("/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: uuid.UUID,
    data: ContactUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> ContactRead:
    return ContactService(db).update(current_user.organization_id, contact_id, data, actor_user_id=current_user.id)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role("owner", "admin"))])
def delete_contact(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    ContactService(db).delete(current_user.organization_id, contact_id, actor_user_id=current_user.id)


@router.post("/{contact_id}/roles", response_model=ContactRead)
def add_contact_role(
    contact_id: uuid.UUID,
    data: ContactRoleAssign,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> ContactRead:
    return ContactService(db).add_role(current_user.organization_id, contact_id, data.role_key)


@router.delete("/{contact_id}/roles/{role_key}", response_model=ContactRead)
def remove_contact_role(
    contact_id: uuid.UUID,
    role_key: str,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> ContactRead:
    return ContactService(db).remove_role(current_user.organization_id, contact_id, role_key)


@router.get("/{contact_id}/buyer-requirements", response_model=list[BuyerRequirementRead])
def list_contact_buyer_requirements(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[BuyerRequirementRead]:
    return BuyerRequirementService(db).list_for_contact(current_user.organization_id, contact_id)


@router.post(
    "/{contact_id}/buyer-requirements", response_model=BuyerRequirementRead, status_code=status.HTTP_201_CREATED
)
def create_contact_buyer_requirement(
    contact_id: uuid.UUID,
    data: BuyerRequirementCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> BuyerRequirementRead:
    return BuyerRequirementService(db).create(
        current_user.organization_id, contact_id, data, actor_user_id=current_user.id
    )


@router.get("/{contact_id}/property-interests", response_model=list[PropertyInterestRead])
def list_contact_property_interests(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[PropertyInterestRead]:
    return PropertyInterestService(db).list_for_contact(current_user.organization_id, contact_id)


@router.post(
    "/{contact_id}/property-interests", response_model=PropertyInterestRead, status_code=status.HTTP_201_CREATED
)
def create_contact_property_interest(
    contact_id: uuid.UUID,
    data: PropertyInterestCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyInterestRead:
    return PropertyInterestService(db).create(current_user.organization_id, contact_id, data)


@router.get("/{contact_id}/activities", response_model=list[ActivityRead])
def list_contact_activities(
    contact_id: uuid.UUID,
    activity_type: ActivityType | None = Query(None),
    occurred_from: datetime | None = Query(None),
    occurred_to: datetime | None = Query(None),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[ActivityRead]:
    """A contact's timeline, oldest first — see app/services/activity_service.py."""
    return ActivityService(db).list_for_contact(
        current_user.organization_id,
        contact_id,
        activity_type=activity_type,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )


@router.post("/{contact_id}/activities", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
def create_contact_activity(
    contact_id: uuid.UUID,
    data: ActivityCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> ActivityRead:
    return ActivityService(db).create(current_user.organization_id, contact_id, current_user.id, data)
