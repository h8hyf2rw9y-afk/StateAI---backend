"""
The Pipeline Agent's structured output — see app/ai/pipeline_agent.py. Same
two-layer split as app/schemas/lead_intelligence.py and
app/schemas/follow_up.py, for the same reason:

- PipelineAnalysis is exactly what the LLM is asked to produce (its JSON
  schema is the forced structured-output shape both providers are
  constrained to). It contains only the model's own judgment.
- PipelineResult is what this backend actually returns to a caller: the
  analysis plus provenance the agent fills in itself.

Deliberate deviation from a bare field-list: `contact_id` lives on
PipelineResult, not inside PipelineAnalysis, even though every individual
recommendation/action/risk item *does* carry its own `opportunity_id`.
Reasoning: the caller already knows which contact was analyzed (it's the
function argument), so asking the LLM to also faithfully reproduce that
single UUID would only add a chance of it getting typo'd or mismatched —
exactly the same reasoning LeadIntelligenceResult/FollowUpResult already
apply for their own `contact_id`. `opportunity_id` is different: a contact
can have *several* opportunities, so the model genuinely has to tell us
which one each item is about — there is no wrapper-level equivalent for that.

This agent answers yet another different question than the other two
(app/ai/prompts/pipeline.py has the full distinction): not "how important
is this lead" (Lead Intelligence) or "does this lead need contact right
now" (Follow-up), but "where does this contact's pipeline of Opportunities
stand, and what does the advisor need to do about it."
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import LeadPriority, PipelineAction, TaskPriority


class OpportunityRecommendation(BaseModel):
    opportunity_id: uuid.UUID = Field(description="Which Opportunity (from the supplied context) this recommendation is about.")
    priority: LeadPriority = Field(
        description="How urgently this specific opportunity deserves the advisor's attention right now — not simply its probability field."
    )
    status_assessment: str = Field(
        description="A concise, factual read of where this opportunity stands right now (e.g. 'Active, no activity in 9 days despite an upcoming appointment') — traceable to the supplied context, not a category."
    )
    reason: str = Field(
        description="Why this priority/assessment — must be traceable to specific facts in the provided context, not invented ones."
    )
    recommended_action: PipelineAction = Field(description="The single most practical next action for this specific opportunity.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="The model's own confidence in this item, as a decimal between 0.0 and 1.0 (for example 0.85). Never a percentage.",
    )


class ImmediateAction(BaseModel):
    opportunity_id: uuid.UUID = Field(description="Which Opportunity this action applies to.")
    action: PipelineAction
    reason: str = Field(description="Why this action is needed now — traceable to the supplied context.")
    urgency: TaskPriority = Field(description="How soon this needs to happen.")


class RiskFlag(BaseModel):
    opportunity_id: uuid.UUID = Field(description="Which Opportunity this risk applies to.")
    risk: str = Field(
        description="A concise, factual description of the risk observed (e.g. 'High expected_value with no activity in 12 days') — not a fixed category."
    )
    reason: str = Field(description="The specific facts in the context that support this risk — not invented ones.")
    severity: LeadPriority


class PipelineAnalysis(BaseModel):
    overall_priority: LeadPriority = Field(
        description="This contact's pipeline as a whole, considering every opportunity together — not just the single highest-priority one."
    )
    summary: str = Field(description="A short, factual summary of this contact's pipeline state as a whole.")
    opportunities: list[OpportunityRecommendation] = Field(
        default_factory=list,
        description="One entry per Opportunity in the supplied context that the advisor should be aware of — reasoned about independently, never merged together.",
    )
    immediate_actions: list[ImmediateAction] = Field(
        default_factory=list, description="Concrete next actions the advisor should take now, across any of this contact's opportunities."
    )
    risk_flags: list[RiskFlag] = Field(
        default_factory=list, description="Specific risks detected from the combination of signals in the context — never a generic/arbitrary rule."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "The model's own confidence in this overall analysis, as a decimal between 0.0 and 1.0 (for example 0.85). "
            "Never a percentage (not 85, not 85.0)."
        ),
    )


class PipelineResult(BaseModel):
    contact_id: uuid.UUID
    analysis: PipelineAnalysis
    model: str
    prompt_version: str
    generated_at: datetime
