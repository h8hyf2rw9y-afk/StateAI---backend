import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.ai.lead_context_tool import get_lead_context
from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.lead_context import LeadContext
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/lead-context/{contact_id}", response_model=LeadContext)
def read_lead_context(
    contact_id: uuid.UUID,
    activity_limit: int = Query(default=20, ge=0, le=200),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> LeadContext:
    """
    Internal/debugging surface for the AI Context Layer — calls the exact
    same get_lead_context tool a future in-process agent will call, through
    the same auth stack as every other route. Not meant for the frontend UI;
    see app/ai/lead_context_tool.py for why this exists.
    """
    return get_lead_context(current_user, contact_id, db, activity_limit=activity_limit)
