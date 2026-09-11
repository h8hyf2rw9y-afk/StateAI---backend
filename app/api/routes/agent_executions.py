import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.agent_execution import AgentExecutionHumanActionUpdate, AgentExecutionLatestRead, AgentExecutionRead
from app.schemas.user import CurrentUser
from app.services.agent_execution_service import AgentExecutionService
from app.services.lead_context_service import LeadContextService

router = APIRouter(prefix="/ai/agent-executions", tags=["ai"])


@router.get("/latest", response_model=AgentExecutionLatestRead | None)
def get_latest_agent_execution(
    contact_id: uuid.UUID = Query(...),
    agent_name: str = Query(...),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> AgentExecutionLatestRead | None:
    """
    "What's the latest valid result for this contact + this agent, and is
    it still fresh?" — the one call the AI Assistant makes when a client is
    selected, to restore a previous analysis instead of re-running the LLM
    (see features/ai/components/*-panel.tsx). A READ only: never creates,
    modifies, or re-runs anything. Returns null when this (contact, agent)
    pair has no successful execution yet — the frontend's empty state.

    Registered before "/{execution_id}" (still matches "latest" as a path
    param otherwise) — same ordering rule FastAPI already needs for any
    literal path segment ahead of a dynamic one.
    """
    execution = AgentExecutionService(db).get_latest_succeeded(
        current_user.organization_id, contact_id=contact_id, agent_name=agent_name
    )
    if execution is None:
        return None

    stored_fingerprint = (execution.input_snapshot or {}).get("context_fingerprint")
    if stored_fingerprint is None:
        # Pre-dates this feature, or fingerprinting failed at write time
        # (see _run_and_record's try/except). There's no evidence either
        # way that the context changed, so this defaults to NOT stale
        # rather than nagging the advisor with an unexplainable "new
        # information available" banner — see AgentExecutionLatestRead's
        # own docstring. A manual Refresh is always available regardless.
        is_stale = False
    else:
        current_fingerprint = LeadContextService(db).compute_context_fingerprint(
            current_user.organization_id, execution.contact_id
        )
        is_stale = current_fingerprint != stored_fingerprint

    return AgentExecutionLatestRead(**AgentExecutionRead.model_validate(execution).model_dump(), is_stale=is_stale)


@router.get("", response_model=list[AgentExecutionRead])
def list_agent_executions(
    contact_id: uuid.UUID | None = Query(None),
    agent_name: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[AgentExecutionRead]:
    """"What did the AI recommend?" — a history of every agent run for this organization, optionally filtered to one contact/agent."""
    return AgentExecutionService(db).list(
        current_user.organization_id, contact_id=contact_id, agent_name=agent_name, limit=limit, offset=offset
    )


@router.get("/{execution_id}", response_model=AgentExecutionRead)
def get_agent_execution(
    execution_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> AgentExecutionRead:
    return AgentExecutionService(db).get_or_404(current_user.organization_id, execution_id)


@router.patch("/{execution_id}", response_model=AgentExecutionRead)
def update_agent_execution_human_action(
    execution_id: uuid.UUID,
    data: AgentExecutionHumanActionUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> AgentExecutionRead:
    """Records whether an advisor acted on or dismissed this recommendation. The only client-writable field on an AgentExecution."""
    return AgentExecutionService(db).set_human_action(current_user.organization_id, execution_id, data.human_action)
