"""
Single source of truth for every "soft enum" in this schema — plain
strings in the database (see the models), validated only here at the API
boundary via Pydantic `Literal` types. Adding a new value later is a
one-line change in this file, never a migration. Mirrors how the frontend
centralizes its own enums (e.g. PIPELINE_STAGES in features/pipeline/types.ts).

Each value set is defined once as a tuple (for runtime use — iterating,
seeding lookup tables, exposing via an API) and mirrored as a `Literal`
type (for Pydantic/static-typing use). Keep the two in sync by hand.
"""

from typing import Literal

USER_ROLES: tuple[str, ...] = ("owner", "admin", "agent")
UserRole = Literal["owner", "admin", "agent"]

CONTACT_SOURCES: tuple[str, ...] = (
    "inmuebles24",
    "lamudi",
    "facebook",
    "marketplace",
    "instagram",
    "website",
    "referral",
    "phone",
    "walk_in",
    "other",
    "unknown",
)
ContactSource = Literal[
    "inmuebles24",
    "lamudi",
    "facebook",
    "marketplace",
    "instagram",
    "website",
    "referral",
    "phone",
    "walk_in",
    "other",
    "unknown",
]

PREFERRED_CONTACT_METHODS: tuple[str, ...] = ("phone", "email", "whatsapp", "sms")
PreferredContactMethod = Literal["phone", "email", "whatsapp", "sms"]

CONTACT_ROLE_KEYS: tuple[str, ...] = ("buyer", "seller", "owner", "investor", "agent", "other")
ContactRoleKey = Literal["buyer", "seller", "owner", "investor", "agent", "other"]

PROPERTY_TYPES: tuple[str, ...] = ("house", "apartment", "land", "commercial", "office", "industrial", "other")
PropertyType = Literal["house", "apartment", "land", "commercial", "office", "industrial", "other"]

PROPERTY_STATUSES: tuple[str, ...] = (
    "draft",
    "active",
    "under_offer",
    "reserved",
    "sold",
    "rented",
    "inactive",
)
PropertyStatus = Literal["draft", "active", "under_offer", "reserved", "sold", "rented", "inactive"]

BUYER_REQUIREMENT_PURPOSES: tuple[str, ...] = ("buy", "rent", "invest")
BuyerRequirementPurpose = Literal["buy", "rent", "invest"]

BUYER_REQUIREMENT_STATUSES: tuple[str, ...] = ("active", "paused", "fulfilled", "cancelled")
BuyerRequirementStatus = Literal["active", "paused", "fulfilled", "cancelled"]

TIMELINES: tuple[str, ...] = ("immediate", "1_3_months", "3_6_months", "6_12_months", "exploring")
Timeline = Literal["immediate", "1_3_months", "3_6_months", "6_12_months", "exploring"]

FINANCING_TYPES: tuple[str, ...] = ("cash", "mortgage", "mixed")
FinancingType = Literal["cash", "mortgage", "mixed"]

PREAPPROVAL_STATUSES: tuple[str, ...] = ("not_started", "in_process", "preapproved", "approved")
PreapprovalStatus = Literal["not_started", "in_process", "preapproved", "approved"]

FEATURE_CLASSIFICATIONS: tuple[str, ...] = ("must_have", "preferred", "deal_breaker")
FeatureClassification = Literal["must_have", "preferred", "deal_breaker"]

PROPERTY_INTEREST_STATUSES: tuple[str, ...] = (
    "new",
    "contacted",
    "interested",
    "viewing_scheduled",
    "viewed",
    "not_interested",
    "offer",
    "negotiation",
    "lost",
    "won",
)
PropertyInterestStatus = Literal[
    "new",
    "contacted",
    "interested",
    "viewing_scheduled",
    "viewed",
    "not_interested",
    "offer",
    "negotiation",
    "lost",
    "won",
]

ACTIVITY_TYPES: tuple[str, ...] = (
    "call",
    "whatsapp",
    "email",
    "property_viewing",
    "follow_up",
    "meeting",
    "note",
    "offer",
    "negotiation",
)
ActivityType = Literal[
    "call", "whatsapp", "email", "property_viewing", "follow_up", "meeting", "note", "offer", "negotiation"
]

ACTIVITY_DIRECTIONS: tuple[str, ...] = ("inbound", "outbound")
ActivityDirection = Literal["inbound", "outbound"]

# app/schemas/lead_intelligence.py — the Lead Intelligence Agent's own
# structured output, same soft-enum treatment as every CRM-facing field.
LEAD_PRIORITIES: tuple[str, ...] = ("high", "medium", "low")
LeadPriority = Literal["high", "medium", "low"]

RECOMMENDED_NEXT_ACTIONS: tuple[str, ...] = (
    "call",
    "whatsapp",
    "email",
    "schedule_viewing",
    "send_properties",
    "follow_up",
    "meeting",
    "re_engage",
    "no_action_needed",
)
RecommendedNextAction = Literal[
    "call", "whatsapp", "email", "schedule_viewing", "send_properties", "follow_up", "meeting", "re_engage", "no_action_needed"
]

# app/schemas/follow_up.py — the Follow-up Agent's own structured output.
# `priority` there reuses LeadPriority directly (same three values, no
# separate tuple needed) since a follow-up's urgency and a lead's overall
# priority share the same high/medium/low scale.
FOLLOW_UP_CHANNELS: tuple[str, ...] = ("whatsapp", "email", "call", "none")
FollowUpChannel = Literal["whatsapp", "email", "call", "none"]

FOLLOW_UP_ACTIONS: tuple[str, ...] = (
    "follow_up",
    "send_properties",
    "confirm_viewing",
    "check_in",
    "call_client",
    "prepare_for_appointment",
    "no_action",
)
FollowUpAction = Literal[
    "follow_up", "send_properties", "confirm_viewing", "check_in", "call_client", "prepare_for_appointment", "no_action"
]
