import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.agent_execution import AgentExecutionHumanActionUpdate, AgentExecutionRead
from app.schemas.user import CurrentUser
from app.services.agent_execution_service import AgentExecutionService

router = APIRouter(prefix="/ai/agent-executions", tags=["ai"])


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
