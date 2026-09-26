import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.enums import RenovaCaseStatus
from app.schemas.renova_case import (
    RenovaCaseCreate,
    RenovaCaseListItem,
    RenovaCaseRead,
    RenovaCaseUpdate,
    RenovaPipelineResponse,
    RenovaSensitiveData,
    RenovaIneImage,
)
from app.schemas.user import CurrentUser
from app.services.renova_case_service import RenovaCaseService

# Renova is its own module: separate prefix, table, service and schemas from
# /contacts and friends. There is intentionally NO delete route — a case that
# should no longer be pursued is moved to status "cancelled" (and audited).
router = APIRouter(prefix="/renova/cases", tags=["renova"])

# A second, small router for /renova/pipeline (NOT nested under /renova/cases
# — it returns many cases already grouped by stage, a different shape from
# the plain listing above). Stage moves reuse PATCH /renova/cases/{id} as-is:
# it already validates the case belongs to this organization and already
# records RENOVA_CASE_STATUS_CHANGED when `status` changes, so there is
# nothing pipeline-specific to add there.
pipeline_router = APIRouter(prefix="/renova", tags=["renova"])


@pipeline_router.get("/pipeline", response_model=RenovaPipelineResponse)
def get_renova_pipeline(
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RenovaPipelineResponse:
    """The Renova Kanban board: every case in an active pipeline stage, grouped by stage. Never NSS, credit number, INE images or ciphertext."""
    return RenovaCaseService(db).pipeline(current_user.organization_id)


@router.get("", response_model=list[RenovaCaseListItem])
def list_renova_cases(
    q: str | None = Query(None, max_length=100, description="Matches the owner's name or phone."),
    status_: RenovaCaseStatus | None = Query(None, alias="status"),
    assigned_user_id: uuid.UUID | None = Query(None),
    archived: bool | None = Query(None, description="Omitted -> only non-archived cases. true -> only archived ones."),
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
        archived=archived,
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


@router.get("/{case_id}/sensitive-data", response_model=RenovaSensitiveData)
def reveal_renova_sensitive_data(
    case_id: uuid.UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RenovaSensitiveData:
    """
    The full NSS and credit number of one case — the only endpoint that ever
    returns them. Authorized (owner/admin or the assigned advisor), audited
    without the values, and never cacheable.
    """
    data = RenovaCaseService(db).reveal_sensitive_data(current_user, case_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return data


@router.get("/{case_id}/ine/{side}", response_model=RenovaIneImage)
def get_renova_ine(case_id: uuid.UUID, side: str, response: Response,
                   current_user: CurrentUser = Depends(get_current_org_user), db: Session = Depends(get_db)) -> RenovaIneImage:
    if side not in ("front", "back"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    image = RenovaCaseService(db).get_ine_image(current_user, case_id, side)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "INE image not found.")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return RenovaIneImage(image=image)


@router.put("/{case_id}/ine/{side}", status_code=status.HTTP_204_NO_CONTENT)
def put_renova_ine(case_id: uuid.UUID, side: str, data: RenovaIneImage,
                   current_user: CurrentUser = Depends(get_current_org_user), db: Session = Depends(get_db)) -> Response:
    if side not in ("front", "back"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    RenovaCaseService(db).save_ine_image(current_user, case_id, side, data.image)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.patch("/{case_id}", response_model=RenovaCaseRead)
def update_renova_case(
    case_id: uuid.UUID,
    data: RenovaCaseUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RenovaCaseRead:
    return RenovaCaseService(db).update(current_user.organization_id, case_id, data, actor_user_id=current_user.id)
