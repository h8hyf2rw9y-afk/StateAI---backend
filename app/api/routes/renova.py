import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.enums import RenovaCaseStatus
from app.schemas.renova_case import RenovaCaseCreate, RenovaCaseListItem, RenovaCaseRead, RenovaCaseUpdate
from app.schemas.user import CurrentUser
from app.services.renova_case_service import RenovaCaseService

# Renova is its own module: separate prefix, table, service and schemas from
# /contacts and friends. There is intentionally NO delete route — a case that
# should no longer be pursued is moved to status "cancelled" (and audited).
router = APIRouter(prefix="/renova/cases", tags=["renova"])


@router.get("", response_model=list[RenovaCaseListItem])
def list_renova_cases(
    q: str | None = Query(None, max_length=100, description="Matches the owner's name or phone."),
    status_: RenovaCaseStatus | None = Query(None, alias="status"),
    assigned_user_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[RenovaCaseListItem]:
    """The Leads → Renova table. Lean rows only: never NSS / credit number, not even masked."""
    return RenovaCaseService(db).list(
        current_user.organization_id,
        q=q,
        status_=status_,
        assigned_user_id=assigned_user_id,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=RenovaCaseRead, status_code=status.HTTP_201_CREATED)
def create_renova_case(
    data: RenovaCaseCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RenovaCaseRead:
    return RenovaCaseService(db).create(current_user.organization_id, data, actor_user_id=current_user.id)


@router.get("/{case_id}", response_model=RenovaCaseRead)
def get_renova_case(
    case_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RenovaCaseRead:
    return RenovaCaseService(db).get(current_user.organization_id, case_id)


@router.patch("/{case_id}", response_model=RenovaCaseRead)
def update_renova_case(
    case_id: uuid.UUID,
    data: RenovaCaseUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RenovaCaseRead:
    return RenovaCaseService(db).update(current_user.organization_id, case_id, data, actor_user_id=current_user.id)
