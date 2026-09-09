import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.ai.follow_up_agent import FollowUpAgent
from app.ai.lead_context_tool import get_lead_context
from app.ai.lead_intelligence_agent import LeadIntelligenceAgent
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMConfigError, LLMInvalidOutputError, LLMProviderError, LLMTimeoutError
from app.ai.llm.factory import build_default_provider
from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.follow_up import FollowUpResult
from app.schemas.lead_context import LeadContext
from app.schemas.lead_intelligence import LeadIntelligenceResult
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_llm_provider() -> LLMProvider:
    """
    FastAPI dependency wrapper around build_default_provider — exists so a
    missing/misconfigured provider becomes an HTTP 503 here (the route's
    concern) instead of build_default_provider itself needing to know about
    HTTPException (it stays a plain, independently testable function that
    raises LLMConfigError). Also the seam tests override to inject a fake
    provider without any real API key or network call.
    """
    try:
        return build_default_provider()
    except LLMConfigError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI analysis service is not configured.") from exc


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


@router.post("/lead-intelligence/{contact_id}", response_model=LeadIntelligenceResult)
def analyze_lead(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(_get_llm_provider),
) -> LeadIntelligenceResult:
    """
    Runs the Lead Intelligence Agent (app/ai/lead_intelligence_agent.py) for
    one contact: builds its LeadContext, asks the configured LLM to analyze
    it, and returns the validated structured result. Read-only — this never
    modifies any CRM data and never contacts the lead.
    """
    agent = LeadIntelligenceAgent(db, llm)
    try:
        return agent.analyze(current_user, contact_id)
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The AI analysis service timed out.") from exc
    except LLMInvalidOutputError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI analysis service returned an unexpected response.") from exc
    except LLMProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI analysis service is currently unavailable.") from exc


@router.post("/follow-up/{contact_id}", response_model=FollowUpResult)
def recommend_follow_up(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(_get_llm_provider),
) -> FollowUpResult:
    """
    Runs the Follow-up Agent (app/ai/follow_up_agent.py) for one contact:
    builds its LeadContext, asks the configured LLM whether this lead needs
    follow-up right now and through which channel, and returns the
    validated structured recommendation. Read-only and advisory only — this
    never modifies any CRM data, sends any message, or creates any
    appointment; a human advisor decides whether to act on it.
    """
    agent = FollowUpAgent(db, llm)
    try:
        return agent.recommend(current_user, contact_id)
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The AI analysis service timed out.") from exc
    except LLMInvalidOutputError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI analysis service returned an unexpected response.") from exc
    except LLMProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI analysis service is currently unavailable.") from exc
