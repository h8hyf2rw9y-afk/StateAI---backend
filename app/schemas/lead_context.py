"""
The structured "everything relevant about this lead" object the AI Context
Layer assembles — see app/services/lead_context_service.py and
app/ai/lead_context_tool.py. Deliberately a tree of typed fields, not a
concatenated text blob: a future agent (or its prompt-building code) reads
specific fields instead of parsing prose.

`engagement_summary` is the one place this file computes anything — and it
only ever aggregates existing facts (a count, a max date, a day
difference). It never scores or judges (no ai_score, no
conversion_probability, no hot/warm/cold classification — that line was
drawn for the demo data and holds here too, now extended to Opportunities:
`is_active` on OpportunityContext is a plain derivation from `stage`
membership in OPPORTUNITY_CLOSED_STAGES, not a judgment): inferring what a
fact *means* is a future agent's job, not this layer's.

Opportunities, Tasks, and Appointments (added alongside the original
Contact/BuyerRequirement/PropertyInterest/Activity fields) follow the same
"typed references over duplication" rule already used for
PropertyInterestContext.property_id: OpportunityContext embeds a small
`property`/`buyer_requirement` *summary* (there's at most one of each per
opportunity, so this is cheap and makes an opportunity self-contained) but
never embeds full Activity/Task/Appointment objects — it carries
`activity_ids`/`task_ids`/`appointment_ids` instead, referencing into the
top-level `activities`/`tasks`/`appointments` lists a caller already has.
This avoids duplicating those lists once per opportunity while still making
"what belongs to this opportunity" directly answerable.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ContactContext(ORMModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    preferred_contact_method: str | None
    source: str | None
    notes: str | None
    roles: list[str]
    created_at: datetime


class BuyerRequirementLocationContext(ORMModel):
    city: str | None
    neighborhood: str | None
    priority: int


class BuyerRequirementFeatureContext(ORMModel):
    feature_key: str
    classification: str


class BuyerRequirementContext(ORMModel):
    id: uuid.UUID
    status: str
    purpose: str | None
    budget_min: Decimal | None
    budget_max: Decimal | None
    currency: str
    property_type: str | None
    bedrooms_min: int | None
    bathrooms_min: Decimal | None
    construction_m2_min: Decimal | None
    land_m2_min: Decimal | None
    parking_spaces_min: int | None
    timeline: str | None
    financing_type: str | None
    preapproval_status: str | None
    motivation: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    locations: list[BuyerRequirementLocationContext]
    features: list[BuyerRequirementFeatureContext]


class PropertyInterestContext(ORMModel):
    id: uuid.UUID
    property_id: uuid.UUID
    status: str
    source: str | None
    notes: str | None
    first_contact_at: datetime | None
    last_contact_at: datetime | None
    created_at: datetime


class PropertyContext(ORMModel):
    id: uuid.UUID
    title: str
    property_type: str
    status: str
    price: Decimal | None
    currency: str
    city: str | None
    state: str | None
    neighborhood: str | None
    bedrooms: int | None
    bathrooms: Decimal | None
    construction_m2: Decimal | None
    land_m2: Decimal | None
    parking_spaces: int | None
    description: str | None


class ActivityContext(ORMModel):
    id: uuid.UUID
    activity_type: str
    direction: str | None
    property_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    occurred_at: datetime
    notes: str


class TaskContext(ORMModel):
    """"What needs to be done" — distinct from ActivityContext ("what already happened"). Kept minimal: no assigned_to_user_id/created_by_user_id — this context is contact-centric, not "my task list," so who's assigned isn't relevant here yet."""

    id: uuid.UUID
    opportunity_id: uuid.UUID | None
    property_id: uuid.UUID | None
    title: str
    description: str | None
    task_type: str
    status: str
    priority: str
    due_at: datetime
    completed_at: datetime | None


class AppointmentContext(ORMModel):
    """"What is scheduled" — distinct from both ActivityContext (what happened) and TaskContext (an open action item with no fixed time)."""

    id: uuid.UUID
    opportunity_id: uuid.UUID | None
    property_id: uuid.UUID | None
    title: str
    description: str | None
    appointment_type: str
    status: str
    start_at: datetime
    end_at: datetime
    location: str | None


class OpportunityPropertySummary(ORMModel):
    """A concise summary, not the full PropertyContext (already available, deduplicated, in LeadContext.properties) — kept here too since exactly one property (if any) applies per opportunity, so the opportunity reads as self-contained without forcing a cross-reference lookup. ORMModel (not a plain BaseModel), like every other class in this file built directly from an ORM object via .model_validate()."""

    id: uuid.UUID
    title: str
    property_type: str
    status: str
    price: Decimal | None
    city: str | None


class OpportunityBuyerRequirementSummary(ORMModel):
    id: uuid.UUID
    status: str
    property_type: str | None
    budget_min: Decimal | None
    budget_max: Decimal | None


class OpportunityContext(BaseModel):
    """
    "What business process is this part of" — the actual sales process an
    advisor is managing, distinct from BuyerRequirement (criteria/intent)
    and PropertyInterest (interest in one listing). See
    app/models/opportunity.py and the README's Opportunities / Pipeline
    section for the full domain model this mirrors.

    `is_active` is derived (stage not in OPPORTUNITY_CLOSED_STAGES), never
    a stored field — see OPPORTUNITY_CLOSED_STAGES in app/schemas/enums.py,
    the same set OpportunityRepository's own is_closed filter already uses.
    No `is_active`-only view is offered here: closed opportunities (won or
    lost) stay in the list, since a contact's history — including deals
    that didn't work out — is real context a future agent needs, not noise
    to discard. "How long has this opportunity been in its current stage?"
    is intentionally not a field here either: it's answerable from the
    timeline (the most recent "stage_change" Activity/timeline entry for
    this opportunity, cross-referenced via activity_ids/the timeline's
    related_id) rather than adding a second, easily-stale "stage_entered_at"
    column no other part of this schema maintains.
    """

    id: uuid.UUID
    contact_id: uuid.UUID
    opportunity_type: str
    stage: str
    is_active: bool
    title: str
    description: str | None
    expected_value: Decimal | None
    currency: str
    probability: int | None
    expected_close_date: datetime | None
    closed_at: datetime | None
    lost_reason: str | None
    owner_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    property: OpportunityPropertySummary | None
    buyer_requirement: OpportunityBuyerRequirementSummary | None
    activity_ids: list[uuid.UUID]
    task_ids: list[uuid.UUID]
    appointment_ids: list[uuid.UUID]


class TimelineEvent(BaseModel):
    """
    One merged, chronological (oldest-first) view across activities,
    property interests, buyer requirements, and opportunities — the one
    list an agent can read start-to-finish as "this lead's story," instead
    of interleaving four separate lists itself. Opportunity *stage changes*
    deliberately do NOT get their own event_type here: OpportunityService
    already records every stage change as a `stage_change` Activity (see
    app/services/opportunity_service.py), which already flows into this
    timeline through the normal "activity" event_type below — a second,
    parallel history of the same fact was judged to be exactly the
    duplication this schema's docstring warns against. Only an
    opportunity's *creation* gets its own event_type, "opportunity",
    mirroring how buyer_requirement/property_interest creation already do.
    """

    event_type: Literal["activity", "property_interest", "buyer_requirement", "opportunity"]
    occurred_at: datetime
    summary: str
    related_id: uuid.UUID


class EngagementSummary(BaseModel):
    activity_count: int
    last_activity_at: datetime | None
    days_since_last_activity: int | None
    has_active_buyer_requirement: bool
    active_property_interest_count: int
    # Opportunity/Task/Appointment-aware additions — every one below is a
    # plain count or a deterministic date comparison, never a judgment (see
    # the module docstring). "current opportunity stages" (suggested
    # alongside these) was deliberately left out: it's already directly
    # readable from LeadContext.opportunities[].stage, so a second,
    # differently-shaped summary of the same list would be redundant, not
    # additive.
    active_opportunity_count: int
    won_opportunity_count: int
    lost_opportunity_count: int
    pending_task_count: int
    overdue_task_count: int
    upcoming_appointment_count: int


class LeadContext(BaseModel):
    contact: ContactContext
    buyer_requirements: list[BuyerRequirementContext]
    property_interests: list[PropertyInterestContext]
    properties: list[PropertyContext]
    opportunities: list[OpportunityContext]
    activities: list[ActivityContext]
    tasks: list[TaskContext]
    appointments: list[AppointmentContext]
    timeline: list[TimelineEvent]
    engagement_summary: EngagementSummary
    generated_at: datetime
