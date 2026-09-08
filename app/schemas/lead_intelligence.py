"""
The Lead Intelligence Agent's structured output — see
app/ai/lead_intelligence_agent.py. Two layers, deliberately kept separate:

- LeadIntelligenceAnalysis is exactly what the LLM is asked to produce (its
  JSON schema is handed to the provider as the forced tool-call shape — see
  app/ai/llm/anthropic_provider.py). It contains only the model's own
  judgment; it cannot know its own model name or a timestamp, so those
  aren't fields on it.
- LeadIntelligenceResult is what this backend actually returns to a caller:
  the analysis plus provenance the agent fills in itself (which contact,
  which model, which prompt version, when).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import LeadPriority, RecommendedNextAction


class LeadIntelligenceAnalysis(BaseModel):
    priority: LeadPriority = Field(description="How urgently this lead deserves the advisor's attention right now.")
    confidence: float = Field(ge=0.0, le=1.0, description="The model's own confidence in this analysis, from 0 to 1.")
    reasoning: str = Field(
        description="Why this priority and action — must be traceable to specific facts in the provided context, not invented ones."
    )
    positive_signals: list[str] = Field(
        default_factory=list, description="Facts from the context that suggest engagement or buying intent."
    )
    risk_signals: list[str] = Field(
        default_factory=list, description="Facts from the context that suggest disengagement or risk of losing the lead."
    )
    recommended_next_action: RecommendedNextAction = Field(
        description="The single most practical next action for the advisor to take."
    )
    insufficient_data: bool = Field(
        default=False,
        description="True if the CRM context was too sparse to analyze meaningfully — set instead of guessing.",
    )


class LeadIntelligenceResult(BaseModel):
    contact_id: uuid.UUID
    analysis: LeadIntelligenceAnalysis
    model: str
    prompt_version: str
    generated_at: datetime
