"""
The AI Gateway: the one place responsible for looking up an agent (via
app/ai/registry.py), invoking it, and recording common execution metadata
(which agent and version, which prompt version, which provider/model
answered, how long it took, whether it succeeded) — so individual agents
never need to know about timing, logging, or which provider is behind the
LLMProvider they were handed. See app/api/routes/ai.py for the only caller
today.

Required flow, unchanged by this layer:
CurrentUser -> organization authorization (inside get_lead_context) ->
LeadContext -> Agent -> LLMProvider -> validated result.

The gateway never touches the database or Supabase directly, never bypasses
organization authorization (that already happened by the time an agent's
`current_user` reaches it), never modifies CRM data, and contains no
agent-specific business logic — only orchestration. It does not select a
provider either; it's handed an already-built LLMProvider (see
app/ai/llm/factory.py) and only ever calls it through the agent.
"""

import logging
import time
import uuid
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMError
from app.ai.registry import get_agent
from app.schemas.user import CurrentUser

logger = logging.getLogger("app.ai.gateway")


@dataclass(frozen=True)
class ExecutionMetadata:
    """
    What every agent execution can report about itself, regardless of which
    agent or provider ran. Deliberately not persisted anywhere yet — see
    scripts/evaluate_agents.py, which is where this gets used today, and the
    project brief: no AI-execution database table until the architecture
    settles. Never includes the LeadContext, any credential, or personal
    data — only bookkeeping about the run itself.
    """

    agent: str
    agent_version: str
    prompt_version: str
    provider: str
    model: str
    duration_ms: int
    success: bool


@dataclass(frozen=True)
class GatewayExecution:
    result: BaseModel
    metadata: ExecutionMetadata


class AIGateway:
    def __init__(self, db: Session, llm: LLMProvider) -> None:
        self.db = db
        self.llm = llm

    def run(self, agent_id: str, current_user: CurrentUser, contact_id: uuid.UUID) -> GatewayExecution:
        """
        Looks up `agent_id` in the registry and invokes it. A 404 from
        context authorization (an unknown or cross-organization contact)
        propagates untouched and is never recorded as execution metadata —
        it's an authorization outcome, not an AI one. Any LLMError subclass
        is logged (agent/provider/model/duration, plus the error's own
        message — never the LeadContext) and re-raised for the caller's
        existing error-to-HTTP mapping (see app/api/routes/ai.py).
        """
        descriptor = get_agent(agent_id)

        started = time.monotonic()
        try:
            result = descriptor.run(self.db, self.llm, current_user, contact_id)
        except LLMError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "ai_gateway.failed agent=%s organization_id=%s provider=%s model=%s duration_ms=%d error=%s",
                agent_id, current_user.organization_id, self.llm.provider_name, self.llm.model_name, duration_ms, exc,
            )
            raise

        duration_ms = int((time.monotonic() - started) * 1000)
        metadata = ExecutionMetadata(
            agent=descriptor.agent_id,
            agent_version=descriptor.version,
            prompt_version=descriptor.prompt_version,
            provider=self.llm.provider_name,
            model=self.llm.model_name,
            duration_ms=duration_ms,
            success=True,
        )
        logger.info(
            "ai_gateway.executed agent=%s organization_id=%s provider=%s model=%s duration_ms=%d success=true",
            agent_id, current_user.organization_id, self.llm.provider_name, self.llm.model_name, duration_ms,
        )
        return GatewayExecution(result=result, metadata=metadata)
