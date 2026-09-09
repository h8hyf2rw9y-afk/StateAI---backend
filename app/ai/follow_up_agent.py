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
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.lead_context_tool import get_lead_context
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMError
from app.ai.prompts.follow_up import FOLLOW_UP_PROMPT_VERSION, FOLLOW_UP_SYSTEM_PROMPT
from app.schemas.follow_up import FollowUpRecommendation, FollowUpResult
from app.schemas.lead_context import LeadContext
from app.schemas.user import CurrentUser

logger = logging.getLogger("app.ai.follow_up")

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

        started = time.monotonic()
        try:
            recommendation = self.llm.generate_structured(
                system_prompt=FOLLOW_UP_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(context),
                response_model=FollowUpRecommendation,
                max_tokens=_MAX_TOKENS,
            )
        except LLMError as exc:
            # The exception's own message carries the actionable, provider-
            # specific detail (e.g. "Is Ollama running?") — logged here so a
            # developer sees it locally. Never sent to the API client: the
            # route only ever returns a generic message for every LLMError
            # subclass (see app/api/routes/ai.py).
            logger.warning(
                "follow_up_agent.failed contact_id=%s organization_id=%s provider=%s model=%s error=%s",
                contact_id, current_user.organization_id, self.llm.provider_name, self.llm.model_name, exc,
            )
            raise

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "follow_up_agent.recommended contact_id=%s organization_id=%s provider=%s model=%s "
            "should_follow_up=%s channel=%s latency_ms=%d",
            contact_id, current_user.organization_id, self.llm.provider_name, self.llm.model_name,
            recommendation.should_follow_up, recommendation.recommended_channel, latency_ms,
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
