"""
The first real AI agent in this codebase: Lead Intelligence. Analyzes one
contact using the already-assembled LeadContext (app/schemas/lead_context.py)
by asking an LLM to judge it — this agent never touches a repository or
Supabase directly, only get_lead_context (the AI Tool).

Flow:
CurrentUser -> get_lead_context -> LeadContext -> LLMProvider ->
LeadIntelligenceAnalysis -> LeadIntelligenceResult

Read-only and provider-agnostic by construction: this agent depends on
LLMProvider (app/ai/llm/base.py), never on a specific vendor SDK, and it has
no way to send a message, modify a contact, or create an activity — it only
returns an analysis for a human advisor to act on.

Kept deliberately thin — timing, logging, and provider/version bookkeeping
now live one layer up in app/ai/gateway.py, so this class only holds this
agent's own reasoning: build the context, ask the model, shape the result.
app/ai/registry.py is what makes this agent reachable through the gateway.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.lead_context_tool import get_lead_context
from app.ai.llm.base import LLMProvider
from app.ai.prompts.lead_intelligence import LEAD_INTELLIGENCE_PROMPT_VERSION, LEAD_INTELLIGENCE_SYSTEM_PROMPT
from app.schemas.lead_context import LeadContext
from app.schemas.lead_intelligence import LeadIntelligenceAnalysis, LeadIntelligenceResult
from app.schemas.user import CurrentUser

# This agent's own implementation/behavior version — distinct from
# LEAD_INTELLIGENCE_PROMPT_VERSION (the prompt text's own version). Bump
# this if the agent's logic or output schema changes in a way that matters
# for comparing runs, independent of prompt wording changes. See
# app/ai/registry.py, where both are recorded together as execution metadata.
LEAD_INTELLIGENCE_AGENT_VERSION = "v1"

_MAX_TOKENS = 1024


class LeadIntelligenceAgent:
    def __init__(self, db: Session, llm: LLMProvider) -> None:
        self.db = db
        self.llm = llm

    def analyze(self, current_user: CurrentUser, contact_id: uuid.UUID) -> LeadIntelligenceResult:
        # Raises HTTPException(404) if the contact doesn't exist or belongs
        # to another organization — same org-scoping every other route gets,
        # enforced here before the LLM is ever called.
        context = get_lead_context(current_user, contact_id, self.db)

        # Any LLMError subclass propagates untouched — app/ai/gateway.py is
        # the one place that catches, times, and logs it.
        analysis = self.llm.generate_structured(
            system_prompt=LEAD_INTELLIGENCE_SYSTEM_PROMPT,
            user_prompt=self._build_user_prompt(context),
            response_model=LeadIntelligenceAnalysis,
            max_tokens=_MAX_TOKENS,
        )

        return LeadIntelligenceResult(
            contact_id=contact_id,
            analysis=analysis,
            model=self.llm.model_name,
            prompt_version=LEAD_INTELLIGENCE_PROMPT_VERSION,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_user_prompt(context: LeadContext) -> str:
        return (
            "Analyze the following lead using ONLY the CRM data below. "
            "Do not invent facts that are not present here.\n\n"
            f"{context.model_dump_json(indent=2)}"
        )
