import time
import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway
from app.ai.lead_context_tool import get_lead_context
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMConfigError, LLMInvalidOutputError, LLMProviderError, LLMTimeoutError
from app.ai.llm.factory import build_default_provider
from app.ai.registry import get_agent
from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.follow_up import FollowUpResult
from app.schemas.lead_context import LeadContext
from app.schemas.lead_intelligence import LeadIntelligenceResult
from app.schemas.user import CurrentUser
from app.services.agent_execution_service import AgentExecutionService

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
    task_limit: int = Query(default=20, ge=0, le=200),
    appointment_limit: int = Query(default=20, ge=0, le=200),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> LeadContext:
    """
    Internal/debugging surface for the AI Context Layer — calls the exact
    same get_lead_context tool a future in-process agent will call, through
    the same auth stack as every other route. Not meant for the frontend UI;
    see app/ai/lead_context_tool.py for why this exists.
    """
    return get_lead_context(
        current_user, contact_id, db, activity_limit=activity_limit, task_limit=task_limit, appointment_limit=appointment_limit
    )


def _run_and_record(agent_id: str, current_user: CurrentUser, contact_id: uuid.UUID, db: Session, llm: LLMProvider):
    """
    Shared by both agent routes below: runs the Gateway, then persists an
    AgentExecution either way (see app/models/agent_execution.py) — one
    place, so a third agent route follows the same pattern by calling this,
    not by re-copying the try/except. Deliberately lives here (not inside
    AIGateway) since the Gateway's own docstring states it never touches
    the database; recording stays this route layer's job, same as mapping
    LLM errors to HTTP status codes already was before this change.

    A 404 from context authorization (unknown/cross-org contact) is not
    caught here — it propagates untouched, same as AIGateway.run() already
    documents, and nothing gets recorded for it (an authorization outcome
    isn't an AI execution outcome).
    """
    descriptor = get_agent(agent_id)
    started = time.monotonic()
    try:
        execution = AIGateway(db, llm).run(agent_id, current_user, contact_id)
    except (LLMTimeoutError, LLMInvalidOutputError, LLMProviderError) as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        AgentExecutionService(db).record_failure(
            organization_id=current_user.organization_id,
            agent_name=agent_id,
            agent_version=descriptor.version,
            contact_id=contact_id,
            user_id=current_user.id,
            provider=llm.provider_name,
            model=llm.model_name,
            duration_ms=duration_ms,
            error=exc,
        )
        if isinstance(exc, LLMTimeoutError):
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The AI analysis service timed out.") from exc
        if isinstance(exc, LLMInvalidOutputError):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "The AI analysis service returned an unexpected response."
            ) from exc
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI analysis service is currently unavailable.") from exc

    AgentExecutionService(db).record_success(
        organization_id=current_user.organization_id,
        agent_name=agent_id,
        agent_version=execution.metadata.agent_version,
        contact_id=contact_id,
        user_id=current_user.id,
        provider=execution.metadata.provider,
        model=execution.metadata.model,
        duration_ms=execution.metadata.duration_ms,
        result=execution.result,
    )
    return execution.result


@router.post("/lead-intelligence/{contact_id}", response_model=LeadIntelligenceResult)
def analyze_lead(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(_get_llm_provider),
) -> LeadIntelligenceResult:
    """
    Runs the Lead Intelligence Agent through the AI Gateway
    (app/ai/gateway.py) for one contact: builds its LeadContext, asks the
    configured LLM to analyze it, and returns the validated structured
    result. Read-only — this never modifies any CRM data and never contacts
    the lead. Every run (success or failure) is persisted as an
    AgentExecution — see _run_and_record above and app/models/agent_execution.py.
    """
    return cast(LeadIntelligenceResult, _run_and_record("lead_intelligence", current_user, contact_id, db, llm))


@router.post("/follow-up/{contact_id}", response_model=FollowUpResult)
def recommend_follow_up(
    contact_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(_get_llm_provider),
) -> FollowUpResult:
    """
    Runs the Follow-up Agent through the AI Gateway (app/ai/gateway.py) for
    one contact: builds its LeadContext, asks the configured LLM whether
    this lead needs follow-up right now and through which channel, and
    returns the validated structured recommendation. Read-only and advisory
    only — this never modifies any CRM data, sends any message, or creates
    any appointment; a human advisor decides whether to act on it. Every
    run (success or failure) is persisted as an AgentExecution — see
    _run_and_record above.
    """
    return cast(FollowUpResult, _run_and_record("follow_up", current_user, contact_id, db, llm))
