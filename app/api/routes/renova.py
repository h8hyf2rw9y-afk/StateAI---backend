import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMConfigError, LLMInvalidOutputError, LLMProviderError, LLMTimeoutError
from app.ai.llm.factory import build_default_provider
from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.enums import RenovaCaseBucket, RenovaCaseStatus
from app.schemas.renova_case import (
    RenovaCaseBucketCounts,
    RenovaCaseCreate,
    RenovaCaseListItem,
    RenovaCaseRead,
    RenovaCaseUpdate,
    RenovaPipelineResponse,
    RenovaSensitiveData,
    RenovaIneImage,
)
from app.schemas.user import CurrentUser
from app.schemas.renova_quick_notes import RenovaQuickNotesExtraction, RenovaQuickNotesRequest
from app.services.renova_case_service import RenovaCaseService
from app.services.renova_quick_notes_service import RenovaQuickNotesService

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


def get_renova_quick_notes_llm() -> LLMProvider:
    try:
        return build_default_provider()
    except LLMConfigError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El extractor de Quick Notes no está configurado.") from exc


@pipeline_router.post("/quick-notes/extract", response_model=RenovaQuickNotesExtraction)
def extract_renova_quick_notes(
    data: RenovaQuickNotesRequest,
    response: Response,
    _current_user: CurrentUser = Depends(get_current_org_user),
    llm: LLMProvider = Depends(get_renova_quick_notes_llm),
) -> RenovaQuickNotesExtraction:
    """Interpret a redacted call note. This route never receives or stores a full NSS, credit number or phone."""
    try:
        result = RenovaQuickNotesService(llm).extract(data.content)
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Quick Notes tardó demasiado en responder.") from exc
    except LLMInvalidOutputError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Quick Notes devolvió datos inesperados.") from exc
    except LLMProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Quick Notes no está disponible en este momento.") from exc
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return result


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
    bucket: RenovaCaseBucket | None = Query(
        None, description="Additive Leads -> Renova tab filter: active, closed (rejected/cancelled), or archived. Overrides `archived` when given; omitted keeps today's `archived`-only behavior."
    ),
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
        bucket=bucket,
        limit=limit,
        offset=offset,
    )


# Registered before GET /{case_id} so FastAPI matches this literal path
# segment first -- otherwise "counts" would be parsed as a case_id and 422.
@router.get("/counts", response_model=RenovaCaseBucketCounts)
def get_renova_case_counts(
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RenovaCaseBucketCounts:
    """Counters for the three Leads → Renova tabs, from one grouped query -- never the case rows themselves."""
    return RenovaCaseService(db).counts(current_user.organization_id)


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
