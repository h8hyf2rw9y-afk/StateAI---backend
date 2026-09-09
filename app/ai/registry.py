"""
The explicit list of AI agents State AI can run today, plus enough
metadata about each to support the AI Gateway (app/ai/gateway.py) and the
evaluation framework (scripts/evaluate_agents.py) — knowing which agent,
which version, which prompt version, and what it consumes/produces,
without either of those needing to know each agent's internals.

Deliberately a plain module-level dict, not a plugin system or anything
reflection-based: adding a third agent (e.g. Sales Copilot, later) means
adding one more AgentDescriptor entry here, never new machinery.
"""

import uuid
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.follow_up_agent import FOLLOW_UP_AGENT_VERSION, FollowUpAgent
from app.ai.lead_intelligence_agent import LEAD_INTELLIGENCE_AGENT_VERSION, LeadIntelligenceAgent
from app.ai.llm.base import LLMProvider
from app.ai.prompts.follow_up import FOLLOW_UP_PROMPT_VERSION
from app.ai.prompts.lead_intelligence import LEAD_INTELLIGENCE_PROMPT_VERSION
from app.schemas.follow_up import FollowUpResult
from app.schemas.lead_context import LeadContext
from app.schemas.lead_intelligence import LeadIntelligenceResult
from app.schemas.user import CurrentUser

# (db, llm, current_user, contact_id) -> the agent's own Result schema instance.
RunFn = Callable[[Session, LLMProvider, CurrentUser, uuid.UUID], BaseModel]


@dataclass(frozen=True)
class AgentDescriptor:
    agent_id: str
    name: str
    description: str
    version: str
    prompt_version: str
    input_type: type[BaseModel]
    output_type: type[BaseModel]
    run: RunFn


AGENT_REGISTRY: dict[str, AgentDescriptor] = {
    "lead_intelligence": AgentDescriptor(
        agent_id="lead_intelligence",
        name="Lead Intelligence Agent",
        description="Judges how important a lead is right now and what the advisor should prioritize.",
        version=LEAD_INTELLIGENCE_AGENT_VERSION,
        prompt_version=LEAD_INTELLIGENCE_PROMPT_VERSION,
        input_type=LeadContext,
        output_type=LeadIntelligenceResult,
        run=lambda db, llm, current_user, contact_id: LeadIntelligenceAgent(db, llm).analyze(current_user, contact_id),
    ),
    "follow_up": AgentDescriptor(
        agent_id="follow_up",
        name="Follow-up Agent",
        description="Decides whether a lead needs follow-up right now, through which channel, and what to say.",
        version=FOLLOW_UP_AGENT_VERSION,
        prompt_version=FOLLOW_UP_PROMPT_VERSION,
        input_type=LeadContext,
        output_type=FollowUpResult,
        run=lambda db, llm, current_user, contact_id: FollowUpAgent(db, llm).recommend(current_user, contact_id),
    ),
}


def get_agent(agent_id: str) -> AgentDescriptor:
    try:
        return AGENT_REGISTRY[agent_id]
    except KeyError:
        raise KeyError(f"Unknown agent_id {agent_id!r}. Known agents: {sorted(AGENT_REGISTRY)}") from None


def list_agents() -> list[AgentDescriptor]:
    return list(AGENT_REGISTRY.values())
