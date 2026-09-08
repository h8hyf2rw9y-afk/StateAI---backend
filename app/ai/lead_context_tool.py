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


def get_lead_context(current_user: CurrentUser, contact_id: uuid.UUID, db: Session, *, activity_limit: int = 20) -> LeadContext:
    """
    Returns the structured Lead Context for one contact.

    Security: `current_user` (not a bare organization_id) is the only
    source of tenant scope — it can only be constructed by
    app.core.security.get_current_org_user from a verified Supabase JWT,
    so there is no parameter here an agent (or a compromised prompt) could
    ever supply to reach another organization's data. Raises HTTPException
    (404) if `contact_id` doesn't resolve within `current_user`'s
    organization — same as every other org-scoped lookup in this codebase.

    Deterministic and side-effect-free: same inputs -> same output (modulo
    `LeadContext.generated_at`), safe to call repeatedly, independently
    testable without a running server or any agent framework.
    """
    return LeadContextService(db).build(current_user.organization_id, contact_id, activity_limit=activity_limit)


# Descriptive metadata only — not wired to any LLM SDK. Documents this
# tool's contract (in the open, provider-agnostic function-calling shape
# most agent frameworks expect) for whoever wires up the actual agent next.
LEAD_CONTEXT_TOOL_SCHEMA: dict = {
    "name": "get_lead_context",
    "description": (
        "Retrieve everything known about one CRM contact/lead: who they are, what they're looking for "
        "(buyer requirements, with preferred locations/features), any specific properties they've shown "
        "interest in, the properties involved, their recent and historical activity, a merged chronological "
        "timeline, and an objective engagement summary (activity count, recency, whether they have an open "
        "buyer requirement or property interest). Read-only; does not modify any data."
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
        },
        "required": ["contact_id"],
    },
}
