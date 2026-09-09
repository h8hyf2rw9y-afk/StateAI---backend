"""
The second real AI agent in this codebase: Follow-up. Determines whether a
contact needs follow-up right now, through which channel, and what the
advisor should say — a different question from Lead Intelligence's "how
important is this lead" (app/ai/lead_intelligence_agent.py). Same
architecture, deliberately: this agent never touches a repository or
Supabase directly, only get_lead_context (the AI Tool).

Flow:
CurrentUser -> get_lead_context -> LeadContext -> LLMProvider ->
FollowUpRecommendation -> FollowUpResult

Read-only and provider-agnostic by construction, exactly like Lead
Intelligence: depends on LLMProvider (app/ai/llm/base.py), never on a
specific vendor SDK, and has no way to send a message, modify a contact,
create an activity, or create an appointment — it only returns a
recommendation for a human advisor to act on.

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
from app.ai.prompts.follow_up import FOLLOW_UP_PROMPT_VERSION, FOLLOW_UP_SYSTEM_PROMPT
from app.schemas.follow_up import FollowUpRecommendation, FollowUpResult
from app.schemas.lead_context import LeadContext
from app.schemas.user import CurrentUser

# This agent's own implementation/behavior version — distinct from
# FOLLOW_UP_PROMPT_VERSION (the prompt text's own version). Bump this if the
# agent's logic or output schema changes in a way that matters for
# comparing runs, independent of prompt wording changes. See
# app/ai/registry.py, where both are recorded together as execution metadata.
FOLLOW_UP_AGENT_VERSION = "v1"

_MAX_TOKENS = 1024


class FollowUpAgent:
    def __init__(self, db: Session, llm: LLMProvider) -> None:
        self.db = db
        self.llm = llm

    def recommend(self, current_user: CurrentUser, contact_id: uuid.UUID) -> FollowUpResult:
        # Raises HTTPException(404) if the contact doesn't exist or belongs
        # to another organization — same org-scoping every other route gets,
        # enforced here before the LLM is ever called.
        context = get_lead_context(current_user, contact_id, self.db)

        # Any LLMError subclass propagates untouched — app/ai/gateway.py is
        # the one place that catches, times, and logs it.
        recommendation = self.llm.generate_structured(
            system_prompt=FOLLOW_UP_SYSTEM_PROMPT,
            user_prompt=self._build_user_prompt(context),
            response_model=FollowUpRecommendation,
            max_tokens=_MAX_TOKENS,
        )

        return FollowUpResult(
            contact_id=contact_id,
            recommendation=recommendation,
            model=self.llm.model_name,
            prompt_version=FOLLOW_UP_PROMPT_VERSION,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_user_prompt(context: LeadContext) -> str:
        return (
            "Decide whether this lead needs follow-up right now, using ONLY the CRM data below. "
            "Do not invent facts that are not present here.\n\n"
            f"{context.model_dump_json(indent=2)}"
        )
