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
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.lead_context_tool import get_lead_context
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMError
from app.ai.prompts.lead_intelligence import LEAD_INTELLIGENCE_PROMPT_VERSION, LEAD_INTELLIGENCE_SYSTEM_PROMPT
from app.schemas.lead_context import LeadContext
from app.schemas.lead_intelligence import LeadIntelligenceAnalysis, LeadIntelligenceResult
from app.schemas.user import CurrentUser

logger = logging.getLogger("app.ai.lead_intelligence")

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

        started = time.monotonic()
        try:
            analysis = self.llm.generate_structured(
                system_prompt=LEAD_INTELLIGENCE_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(context),
                response_model=LeadIntelligenceAnalysis,
                max_tokens=_MAX_TOKENS,
            )
        except LLMError:
            logger.warning(
                "lead_intelligence_agent.failed contact_id=%s organization_id=%s model=%s",
                contact_id, current_user.organization_id, self.llm.model_name,
            )
            raise

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "lead_intelligence_agent.analyzed contact_id=%s organization_id=%s model=%s priority=%s latency_ms=%d",
            contact_id, current_user.organization_id, self.llm.model_name, analysis.priority, latency_ms,
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
