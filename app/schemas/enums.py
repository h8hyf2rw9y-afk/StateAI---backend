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

# app/models/feature.py's Feature.category — the catalog's own grouping,
# distinct from FeatureClassification above (which is how one specific
# buyer requirement rates a feature: must_have/preferred/deal_breaker).
FEATURE_CATEGORIES: tuple[str, ...] = (
    "interior",
    "exterior",
    "amenity",
    "security",
    "location",
    "accessibility",
    "other",
)
FeatureCategory = Literal["interior", "exterior", "amenity", "security", "location", "accessibility", "other"]

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
    "stage_change",
)
ActivityType = Literal[
    "call", "whatsapp", "email", "property_viewing", "follow_up", "meeting", "note", "offer", "negotiation",
    "stage_change",
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

# app/models/agent_execution.py — did this AI execution complete or fail?
# Distinct from the agent's own *content* (e.g. LeadIntelligence's "priority")
# — this is about the execution itself, not what it concluded.
AGENT_EXECUTION_STATUSES: tuple[str, ...] = ("succeeded", "failed")
AgentExecutionStatus = Literal["succeeded", "failed"]

# app/models/agent_execution.py's optional human_action/human_action_at —
# did an advisor do anything with what the AI recommended? Left unset
# (None) until a human actually looks at it; recorded manually today (no
# route auto-sets this), via PATCH /ai/agent-executions/{id}.
HUMAN_ACTION_STATUSES: tuple[str, ...] = ("acted_on", "dismissed")
HumanActionStatus = Literal["acted_on", "dismissed"]

# app/models/task.py — extend by adding a value here, same as every other
# soft enum; DOCUMENT/CONTRACT/NOTARY/PAYMENT/COMMISSION exist now even
# though those modules don't yet, so Tasks referencing them already make
# sense once those modules land.
TASK_TYPES: tuple[str, ...] = (
    "follow_up", "call", "showing", "document", "contract", "notary", "payment", "commission", "other",
)
TaskType = Literal[
    "follow_up", "call", "showing", "document", "contract", "notary", "payment", "commission", "other",
]

TASK_STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed", "cancelled")
TaskStatus = Literal["pending", "in_progress", "completed", "cancelled"]

TASK_PRIORITIES: tuple[str, ...] = ("low", "medium", "high", "urgent")
TaskPriority = Literal["low", "medium", "high", "urgent"]

# app/models/appointment.py
APPOINTMENT_TYPES: tuple[str, ...] = ("showing", "call", "meeting", "notary", "signing", "other")
AppointmentType = Literal["showing", "call", "meeting", "notary", "signing", "other"]

APPOINTMENT_STATUSES: tuple[str, ...] = ("scheduled", "confirmed", "completed", "cancelled", "no_show")
AppointmentStatus = Literal["scheduled", "confirmed", "completed", "cancelled", "no_show"]

# app/models/calendar_connection.py and app/integrations/calendar/ — which
# external calendar this connection/integration targets. Three values exist
# because the interface (CalendarProvider) is being prepared for all three
# now; only stub implementations exist for any of them today — see
# app/integrations/calendar/base.py and the README's Calendar Integration
# Architecture section.
CALENDAR_PROVIDERS: tuple[str, ...] = ("google", "apple", "notion")
CalendarProviderName = Literal["google", "apple", "notion"]

# A connection record's own lifecycle — distinct from Appointment's status.
# "connected" never actually occurs yet: no OAuth flow exists to reach it
# (see README) — it's modeled now so the column doesn't need to change
# once OAuth is implemented.
CALENDAR_CONNECTION_STATUSES: tuple[str, ...] = ("pending", "connected", "expired", "error", "disconnected")
CalendarConnectionStatus = Literal["pending", "connected", "expired", "error", "disconnected"]

# app/models/notification.py
NOTIFICATION_TYPES: tuple[str, ...] = (
    "task_due", "appointment_upcoming", "follow_up_reminder", "document_deadline", "contract_deadline", "system",
)
NotificationType = Literal[
    "task_due", "appointment_upcoming", "follow_up_reminder", "document_deadline", "contract_deadline", "system",
    # Phase 6 — event-driven recommendations (app/automation/detectors.py).
    # Plain new string values on an already-soft-enum column: no migration,
    # same as every value above (NotificationRead.type stays plain `str`,
    # so an older/newer app version can never crash on an unmapped value).
    "contact_missing_requirements", "buyer_requirement_incomplete", "buyer_requirement_ready", "opportunity_inactive",
    # Phase 7 — the completed-appointment follow-up Task's companion
    # notification (app/automation/actions.py's
    # create_completed_appointment_followup_task).
    "followup_task_created",
]

# app/models/opportunity.py — the two sales processes this CRM actively
# manages today. "rent" deliberately excluded even though
# BuyerRequirementPurpose already supports it for a *requirement*: nothing
# in the current stage lifecycle below was designed around a lease-signing
# workflow (distinct from a sale's closing), so adding it now would be
# speculative — extend this the same one-line way once a real rental
# pipeline is needed.
OPPORTUNITY_TYPES: tuple[str, ...] = ("buy", "sell")
OpportunityType = Literal["buy", "sell"]

# One shared, superset stage enum rather than two separate ones — see
# app/services/opportunity_service.py's docstring for the full reasoning.
# In short: a BUY and a SELL pipeline are the *same* pipeline for most of
# their length (offer -> negotiation -> reservation -> contract -> closing
# -> won/lost) and diverge only at the very start (search vs.
# listing/marketing) — two entirely separate enums would duplicate 8 of 13
# values for no benefit. OPPORTUNITY_STAGES_BY_TYPE below (not a second
# enum) is what actually keeps a BUY opportunity out of a SELL-only stage.
OPPORTUNITY_STAGES: tuple[str, ...] = (
    "qualification",
    "search",              # buy-only — actively searching for a matching property
    "listing",              # sell-only — property listed with the agency
    "marketing",              # sell-only — actively promoting the listing
    "property_selected",       # buy-only — a specific property has been chosen to pursue
    "showing",                   # shared — a buyer's viewing IS the seller's showing, same event
    "offer",
    "negotiation",
    "reservation",
    "contract",
    "closing",
    "won",
    "lost",
)
OpportunityStage = Literal[
    "qualification", "search", "listing", "marketing", "property_selected", "showing",
    "offer", "negotiation", "reservation", "contract", "closing", "won", "lost",
]

# Which of the shared stages above are meaningful for each opportunity_type
# — enforced in OpportunityService so a BUY opportunity can't be set to
# "listing" (or a SELL one to "search"). Every other stage is shared.
OPPORTUNITY_STAGES_BY_TYPE: dict[str, tuple[str, ...]] = {
    "buy": (
        "qualification", "search", "property_selected", "showing", "offer", "negotiation",
        "reservation", "contract", "closing", "won", "lost",
    ),
    "sell": (
        "qualification", "listing", "marketing", "showing", "offer", "negotiation",
        "reservation", "contract", "closing", "won", "lost",
    ),
}

# The two terminal stages — an opportunity in either is "closed" (see
# OpportunityRepository.list's is_closed filter and OpportunityService's
# closed_at/lost_reason auto-handling).
OPPORTUNITY_CLOSED_STAGES: frozenset[str] = frozenset({"won", "lost"})

# app/models/opportunity.py's lost_reason — structured, not free text, on
# purpose: "which deals were lost and why" (a named AI-readiness
# requirement) needs to be answerable by grouping/counting, not by an LLM
# parsing prose. Required whenever stage is set to "lost" — see
# OpportunityService._validate_lost_reason.
OPPORTUNITY_LOST_REASONS: tuple[str, ...] = (
    "price",
    "financing_denied",
    "chose_another_property",
    "chose_competitor",
    "unresponsive",
    "changed_mind",
    "timeline_changed",
    "other",
)
OpportunityLostReason = Literal[
    "price", "financing_denied", "chose_another_property", "chose_competitor",
    "unresponsive", "changed_mind", "timeline_changed", "other",
]

# app/schemas/pipeline.py — the Pipeline Agent's own structured output.
# A distinct set from RECOMMENDED_NEXT_ACTIONS (Lead Intelligence) and
# FOLLOW_UP_ACTIONS (Follow-up) on purpose, same as those two are already
# distinct from each other: this agent reasons at the *deal* level (an
# Opportunity's stage/value/close date), so several of its actions
# (review_offer, negotiate, collect_documents, review_financing,
# coordinate_notary, create_task, monitor) don't exist in either of the
# other two vocabularies. Some values overlap in spelling (call, whatsapp,
# email, follow_up, send_properties) because the same real-world action
# is genuinely relevant to more than one question — each agent still gets
# its own Literal type, not a shared one, matching how this file already
# keeps RecommendedNextAction and FollowUpAction independent.
PIPELINE_ACTIONS: tuple[str, ...] = (
    "call",
    "whatsapp",
    "email",
    "follow_up",
    "send_properties",
    "schedule_viewing",
    "prepare_appointment",
    "review_offer",
    "negotiate",
    "collect_documents",
    "review_financing",
    "coordinate_notary",
    "create_task",
    "monitor",
)
PipelineAction = Literal[
    "call", "whatsapp", "email", "follow_up", "send_properties", "schedule_viewing", "prepare_appointment",
    "review_offer", "negotiate", "collect_documents", "review_financing", "coordinate_notary", "create_task",
    "monitor",
]
