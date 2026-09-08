import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.buyer_requirement import BuyerRequirementRead, BuyerRequirementUpdate, FeatureAssign, LocationCreate
from app.schemas.matching import PropertyMatchRead
from app.schemas.user import CurrentUser
from app.services.buyer_requirement_service import BuyerRequirementService
from app.services.matching_service import MatchingService

router = APIRouter(prefix="/buyer-requirements", tags=["buyer-requirements"])


@router.get("", response_model=list[BuyerRequirementRead])
def list_buyer_requirements(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[BuyerRequirementRead]:
    return BuyerRequirementService(db).list(current_user.organization_id, limit=limit, offset=offset)


@router.get("/{requirement_id}", response_model=BuyerRequirementRead)
def get_buyer_requirement(
    requirement_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> BuyerRequirementRead:
    return BuyerRequirementService(db).get_or_404(current_user.organization_id, requirement_id)


@router.patch("/{requirement_id}", response_model=BuyerRequirementRead)
def update_buyer_requirement(
    requirement_id: uuid.UUID,
    data: BuyerRequirementUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> BuyerRequirementRead:
    return BuyerRequirementService(db).update(current_user.organization_id, requirement_id, data)


@router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buyer_requirement(
    requirement_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    BuyerRequirementService(db).delete(current_user.organization_id, requirement_id)


@router.post("/{requirement_id}/locations", response_model=BuyerRequirementRead)
def add_buyer_requirement_location(
    requirement_id: uuid.UUID,
    data: LocationCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> BuyerRequirementRead:
    return BuyerRequirementService(db).add_location(current_user.organization_id, requirement_id, data)


@router.post("/{requirement_id}/features", response_model=BuyerRequirementRead)
def add_buyer_requirement_feature(
    requirement_id: uuid.UUID,
    data: FeatureAssign,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> BuyerRequirementRead:
    return BuyerRequirementService(db).add_feature(current_user.organization_id, requirement_id, data)


@router.get("/{requirement_id}/matches", response_model=list[PropertyMatchRead])
def get_buyer_requirement_matches(
    requirement_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[PropertyMatchRead]:
    """Use Case 5 — deterministic candidate properties for this requirement. See app/services/matching_service.py."""
    matches = MatchingService(db).find_matches(current_user.organization_id, requirement_id, limit=limit)
    return [
        PropertyMatchRead(
            property=m.property,
            matched_preferred_features=m.matched_preferred_features,
            total_preferred_features=m.total_preferred_features,
        )
        for m in matches
    ]
