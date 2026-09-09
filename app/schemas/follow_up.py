"""
The Follow-up Agent's structured output — see app/ai/follow_up_agent.py.
Same two-layer split as app/schemas/lead_intelligence.py, for the same
reason:

- FollowUpRecommendation is exactly what the LLM is asked to produce (its
  JSON schema is the forced structured-output shape both providers are
  constrained to). It contains only the model's own judgment.
- FollowUpResult is what this backend actually returns to a caller: the
  recommendation plus provenance the agent fills in itself.

This agent answers a different question than Lead Intelligence
(app/schemas/lead_intelligence.py): not "how important is this lead", but
"does this lead need follow-up right now, through which channel, and what
should the advisor say" — see app/ai/prompts/follow_up.py for the full
distinction.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import FollowUpAction, FollowUpChannel, LeadPriority


class FollowUpRecommendation(BaseModel):
    should_follow_up: bool = Field(description="Whether this lead needs follow-up from the advisor right now.")
    priority: LeadPriority = Field(description="How urgent this follow-up is, if one is needed.")
    recommended_channel: FollowUpChannel = Field(
        description="The best channel for this follow-up, based on the CRM context. 'none' when should_follow_up is false."
    )
    recommended_action: FollowUpAction = Field(description="The specific action the advisor should take next.")
    reason: str = Field(
        description="Why this recommendation — must be traceable to specific facts in the provided context, not invented ones."
    )
    suggested_message: str | None = Field(
        default=None,
        description=(
            "A short, personalized message ready to send via recommended_channel, grounded only in the supplied "
            "CRM facts — no invented details, no robotic tone. Leave this empty/null when should_follow_up is false."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "The model's own confidence in this recommendation, as a decimal between 0.0 and 1.0 (for example 0.85). "
            "Never a percentage (not 85, not 85.0)."
        ),
    )


class FollowUpResult(BaseModel):
    contact_id: uuid.UUID
    recommendation: FollowUpRecommendation
    model: str
    prompt_version: str
    generated_at: datetime
