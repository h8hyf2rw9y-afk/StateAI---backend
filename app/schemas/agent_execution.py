import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.enums import HumanActionStatus


class AgentExecutionRead(ORMModel):
    """Read-only except for `human_action` — see AgentExecutionHumanActionUpdate below. Written only by app/api/routes/ai.py via AgentExecutionService."""

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_name: str
    agent_version: str
    contact_id: uuid.UUID | None
    user_id: uuid.UUID | None
    input_snapshot: dict | None
    output: dict
    status: str
    provider: str
    model: str
    duration_ms: int | None
    human_action: str | None
    human_action_at: datetime | None
    created_at: datetime


class AgentExecutionLatestRead(AgentExecutionRead):
    """
    Response for GET /ai/agent-executions/latest — the same fields as
    AgentExecutionRead plus one computed field the frontend needs to decide
    which of the three "no result / valid result / stale result" states to
    render (see features/ai/components/*-panel.tsx): `is_stale` compares
    this execution's stored context_fingerprint (see
    LeadContextService.compute_context_fingerprint) against the contact's
    current one. `is_stale` is False (not "unknown") when an older
    execution has no stored fingerprint at all — see the route for why that
    default was chosen.
    """

    is_stale: bool


class AgentExecutionHumanActionUpdate(BaseModel):
    """The only client-writable slice of an AgentExecution — records whether an advisor acted on or dismissed the recommendation. Sets human_action_at server-side."""

    human_action: HumanActionStatus
