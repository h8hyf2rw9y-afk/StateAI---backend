"""
The first AI Tool: get_lead_context. Infrastructure for future agents
(Lead Intelligence first, then Follow-up, Sales Copilot) — not an agent
itself. No LLM call happens anywhere in this file.
"""

import uuid

from sqlalchemy.orm import Session

from app.schemas.lead_context import LeadContext
from app.schemas.user import CurrentUser
from app.services.lead_context_service import LeadContextService


def get_lead_context(
    current_user: CurrentUser,
    contact_id: uuid.UUID,
    db: Session,
    *,
    activity_limit: int = 20,
    task_limit: int = 20,
    appointment_limit: int = 20,
) -> LeadContext:
    """
    Returns the structured Lead Context for one contact.

    Security: `current_user` (not a bare organization_id) is the only
    source of tenant scope — it can only be constructed by
    app.core.security.get_current_org_user from a verified Supabase JWT,
    so there is no parameter here an agent (or a compromised prompt) could
    ever supply to reach another organization's data. Raises HTTPException
    (404) if `contact_id` doesn't resolve within `current_user`'s
    organization — same as every other org-scoped lookup in this codebase.
    This holds for Opportunities/Tasks/Appointments exactly as it already
    did for Buyer Requirements/Property Interests/Activities: every one of
    them is loaded through an organization_id-scoped repository call inside
    LeadContextService.build, never independently, so there is no separate
    path an agent could use to reach another organization's data.

    Deterministic and side-effect-free: same inputs -> same output (modulo
    `LeadContext.generated_at`), safe to call repeatedly, independently
    testable without a running server or any agent framework.
    """
    return LeadContextService(db).build(
        current_user.organization_id,
        contact_id,
        activity_limit=activity_limit,
        task_limit=task_limit,
        appointment_limit=appointment_limit,
    )


# Descriptive metadata only — not wired to any LLM SDK. Documents this
# tool's contract (in the open, provider-agnostic function-calling shape
# most agent frameworks expect) for whoever wires up the actual agent next.
LEAD_CONTEXT_TOOL_SCHEMA: dict = {
    "name": "get_lead_context",
    "description": (
        "Retrieve everything known about one CRM contact/lead: who they are, what they're looking for "
        "(buyer requirements, with preferred locations/features), any specific properties they've shown "
        "interest in, the properties involved, every opportunity (BUY/SELL sales process) this contact is "
        "or was part of — with its stage, expected value/probability/close date, and the property/buyer "
        "requirement it relates to — their pending tasks, upcoming/past appointments, their recent and "
        "historical activity (including opportunity stage changes), a merged chronological timeline, and an "
        "objective engagement summary (activity count, recency, open buyer requirement/property interest, "
        "active/won/lost opportunity counts, pending/overdue task counts, upcoming appointment count). "
        "Read-only; does not modify any data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "contact_id": {"type": "string", "format": "uuid", "description": "The contact/lead's id."},
            "activity_limit": {
                "type": "integer",
                "default": 20,
                "description": "Max number of most-recent activities to include in detail.",
            },
            "task_limit": {
                "type": "integer",
                "default": 20,
                "description": "Max number of tasks to include (this contact's own, plus any tied to one of their opportunities).",
            },
            "appointment_limit": {
                "type": "integer",
                "default": 20,
                "description": "Max number of appointments to include (this contact's own, plus any tied to one of their opportunities).",
            },
        },
        "required": ["contact_id"],
    },
}
