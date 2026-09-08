"""
The structured "everything relevant about this lead" object the AI Context
Layer assembles — see app/services/lead_context_service.py and
app/ai/lead_context_tool.py. Deliberately a tree of typed fields, not a
concatenated text blob: a future agent (or its prompt-building code) reads
specific fields instead of parsing prose.

`engagement_summary` is the one place this file computes anything — and it
only ever aggregates existing facts (a count, a max date, a day
difference). It never scores or judges (no ai_score, no
conversion_probability — that line was drawn for the demo data and holds
here too): inferring what a fact *means* is the future Lead Intelligence
Agent's job, not this layer's.
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
    occurred_at: datetime
    notes: str


class TimelineEvent(BaseModel):
    """
    One merged, chronological (oldest-first) view across activities,
    property interests, and buyer requirements — the one list an agent can
    read start-to-finish as "this lead's story," instead of interleaving
    three separate lists itself.
    """

    event_type: Literal["activity", "property_interest", "buyer_requirement"]
    occurred_at: datetime
    summary: str
    related_id: uuid.UUID


class EngagementSummary(BaseModel):
    activity_count: int
    last_activity_at: datetime | None
    days_since_last_activity: int | None
    has_active_buyer_requirement: bool
    active_property_interest_count: int


class LeadContext(BaseModel):
    contact: ContactContext
    buyer_requirements: list[BuyerRequirementContext]
    property_interests: list[PropertyInterestContext]
    properties: list[PropertyContext]
    activities: list[ActivityContext]
    timeline: list[TimelineEvent]
    engagement_summary: EngagementSummary
    generated_at: datetime
