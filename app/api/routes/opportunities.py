import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.activity import ActivityRead
from app.schemas.enums import OpportunityStage, OpportunityType
from app.schemas.opportunity import OpportunityRead, OpportunityUpdate
from app.schemas.user import CurrentUser
from app.services.activity_service import ActivityService
from app.services.opportunity_service import OpportunityService

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

# No POST here — an Opportunity is always created *for* a contact
# (POST /contacts/{contact_id}/opportunities, app/api/routes/contacts.py),
# same as BuyerRequirement/PropertyInterest/Activity. No DELETE either —
# see app/services/opportunity_service.py's docstring: an Opportunity is
# business history, so "removing" one means setting stage="lost" with a
# lost_reason, not deleting the row.


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(
    opportunity_type: OpportunityType | None = Query(None),
    stage: OpportunityStage | None = Query(None),
    owner_user_id: uuid.UUID | None = Query(None),
    contact_id: uuid.UUID | None = Query(None),
    property_id: uuid.UUID | None = Query(None),
    buyer_requirement_id: uuid.UUID | None = Query(None),
    expected_close_from: datetime | None = Query(None),
    expected_close_to: datetime | None = Query(None),
    is_closed: bool | None = Query(None, description="true = only won/lost, false = only still-open, omitted = both."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[OpportunityRead]:
    return OpportunityService(db).list(
        current_user.organization_id,
        opportunity_type=opportunity_type,
        stage=stage,
        owner_user_id=owner_user_id,
        contact_id=contact_id,
        property_id=property_id,
        buyer_requirement_id=buyer_requirement_id,
        expected_close_from=expected_close_from,
        expected_close_to=expected_close_to,
        is_closed=is_closed,
        limit=limit,
        offset=offset,
    )


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(
    opportunity_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> OpportunityRead:
    return OpportunityService(db).get_or_404(current_user.organization_id, opportunity_id)


@router.patch("/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(
    opportunity_id: uuid.UUID,
    data: OpportunityUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> OpportunityRead:
    """
    Also how a stage changes, including closing (`stage: "won"`) or marking
    lost (`stage: "lost", lost_reason: "..."`) or reopening (moving a
    closed opportunity back to a working stage) — one PATCH, no separate
    action routes. Every stage change auto-stamps/clears `closed_at`,
    creates a `stage_change` Activity, and writes a specifically-named
    audit action (OPPORTUNITY_WON/OPPORTUNITY_LOST/OPPORTUNITY_REOPENED/
    OPPORTUNITY_STAGE_CHANGED) — see app/services/opportunity_service.py.
    """
    return OpportunityService(db).update(current_user.organization_id, opportunity_id, data, actor_user_id=current_user.id)


@router.get("/{opportunity_id}/activities", response_model=list[ActivityRead])
def list_opportunity_activities(
    opportunity_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[ActivityRead]:
    """The deal's own timeline, oldest first — includes every stage-change entry OpportunityService recorded automatically, plus anything else logged with this opportunity_id."""
    return ActivityService(db).list_for_opportunity(current_user.organization_id, opportunity_id)
