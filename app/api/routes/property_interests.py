import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user, require_role
from app.schemas.property_interest import PropertyInterestRead, PropertyInterestUpdate
from app.schemas.user import CurrentUser
from app.services.property_interest_service import PropertyInterestService

router = APIRouter(prefix="/property-interests", tags=["property-interests"])


@router.get("/{interest_id}", response_model=PropertyInterestRead)
def get_property_interest(
    interest_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyInterestRead:
    return PropertyInterestService(db).get_or_404(current_user.organization_id, interest_id)


@router.patch("/{interest_id}", response_model=PropertyInterestRead)
def update_property_interest(
    interest_id: uuid.UUID,
    data: PropertyInterestUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> PropertyInterestRead:
    return PropertyInterestService(db).update(current_user.organization_id, interest_id, data)


@router.delete(
    "/{interest_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role("owner", "admin"))]
)
def delete_property_interest(
    interest_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    PropertyInterestService(db).delete(current_user.organization_id, interest_id)
