"""
The third AI agent in this codebase: Pipeline. Analyzes the complete set of
Opportunities in one contact's LeadContext (app/schemas/lead_context.py) —
priority, risk, staleness, upcoming appointments, overdue tasks — and
returns structured, actionable pipeline recommendations. A different
question again from Lead Intelligence ("how important is this lead right
now") and Follow-up ("does this lead need contact right now, through which
channel"): this one is "where does this contact's pipeline of Opportunities
stand, and what does the advisor need to do about it." This agent never
touches a repository or Supabase directly, only get_lead_context (the AI Tool).

Flow:
CurrentUser -> get_lead_context -> LeadContext -> LLMProvider ->
PipelineAnalysis -> PipelineResult

Read-only and provider-agnostic by construction, exactly like the other two
agents: depends on LLMProvider (app/ai/llm/base.py), never a specific
vendor SDK, and has no way to modify a contact, a property, an opportunity,
a task, an appointment, or send any message — it only returns a
recommendation for a human advisor to act on.

Kept deliberately thin — timing, logging, and provider/version bookkeeping
live one layer up in app/ai/gateway.py, so this class only holds this
agent's own reasoning: build the context, ask the model, shape the result.
app/ai/registry.py is what makes this agent reachable through the gateway.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.lead_context_tool import get_lead_context
from app.ai.llm.base import LLMProvider
from app.ai.prompts.pipeline import PIPELINE_PROMPT_VERSION, PIPELINE_SYSTEM_PROMPT
from app.schemas.lead_context import LeadContext
from app.schemas.pipeline import PipelineAnalysis, PipelineResult
from app.schemas.user import CurrentUser

# This agent's own implementation/behavior version — distinct from
# PIPELINE_PROMPT_VERSION (the prompt text's own version). See
# app/ai/registry.py, where both are recorded together as execution metadata.
PIPELINE_AGENT_VERSION = "v1"

# Higher than the other two agents' 1024: this agent's output can include
# several opportunities/actions/risks (one nested item per Opportunity in
# the contact's pipeline), not a single judgment — measured against real
# demo contacts with multiple opportunities, 1024 was tight.
_MAX_TOKENS = 1536


class PipelineAgent:
    def __init__(self, db: Session, llm: LLMProvider) -> None:
        self.db = db
        self.llm = llm

    def analyze(self, current_user: CurrentUser, contact_id: uuid.UUID) -> PipelineResult:
        # Raises HTTPException(404) if the contact doesn't exist or belongs
        # to another organization — same org-scoping every other route gets,
        # enforced here before the LLM is ever called.
        context = get_lead_context(current_user, contact_id, self.db)

        # Any LLMError subclass propagates untouched — app/ai/gateway.py is
        # the one place that catches, times, and logs it.
        analysis = self.llm.generate_structured(
            system_prompt=PIPELINE_SYSTEM_PROMPT,
            user_prompt=self._build_user_prompt(context),
            response_model=PipelineAnalysis,
            max_tokens=_MAX_TOKENS,
        )

        return PipelineResult(
            contact_id=contact_id,
            analysis=analysis,
            model=self.llm.model_name,
            prompt_version=PIPELINE_PROMPT_VERSION,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_user_prompt(context: LeadContext) -> str:
        return (
            "Analyze this contact's pipeline using ONLY the CRM data below. "
            "Do not invent facts that are not present here.\n\n"
            f"{context.model_dump_json(indent=2)}"
        )
