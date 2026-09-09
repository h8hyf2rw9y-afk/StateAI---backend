"""
Golden test cases for the four demo contacts the AI agents get evaluated
against (see scripts/evaluate_agents.py): Carlos, Gabriela, Carolina,
Sergio. Deliberately separate from any LLM call — these assert only
deterministic CRM facts already known from the seed data (via
LeadContextService, exactly what an agent's prompt is built from), never an
AI conclusion.

The purpose is narrow: if the seed data, LeadContextService, or the
LeadContext schema ever changed in a way that silently dropped or
corrupted one of these facts, this file catches it immediately in the
fast offline suite — before it could ever show up as a hallucination or
context-loss bug in an agent's real output. AI answer quality is judged
separately (scripts/evaluate_agents.py), never here.
"""

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.services.lead_context_service import LeadContextService
from scripts.seed_demo_data import det_id, run_seed


def _context(db_session: Session, org_id, contact_key: str):
    contact_id = db_session.get(Contact, det_id(f"contact:{contact_key}")).id
    return LeadContextService(db_session).build(org_id, contact_id)


def test_carlos_has_an_active_buyer_requirement_and_recent_activity(db_session: Session):
    """Carlos: active buyer requirement exists, recent activity exists, follow-up may be appropriate."""
    org = run_seed(db_session)
    context = _context(db_session, org.id, "carlos-mendoza")

    assert context.engagement_summary.has_active_buyer_requirement is True
    assert any(br.status == "active" for br in context.buyer_requirements)
    assert context.engagement_summary.activity_count > 0
    assert context.engagement_summary.last_activity_at is not None


def test_gabriela_transition_from_rejected_property_to_active_search_is_preserved(db_session: Session):
    """
    Gabriela: previously rejected a property, later created/maintained an
    active buyer requirement — the historical transition must not disappear.
    This is the critical case: losing either fact would be exactly the kind
    of context-loss this golden suite exists to catch.
    """
    org = run_seed(db_session)
    context = _context(db_session, org.id, "gabriela-ortiz")

    rejected = [pi for pi in context.property_interests if pi.status == "not_interested"]
    assert len(rejected) == 1, "the rejected property interest must still be visible, not deleted or overwritten"

    active_requirements = [br for br in context.buyer_requirements if br.status == "active"]
    assert len(active_requirements) == 1, "the buyer requirement she opened afterward must be present"

    # Both facts belong to the same lead's timeline, in the right order.
    rejection_event = next(e for e in context.timeline if e.event_type == "property_interest")
    requirement_event = next(e for e in context.timeline if e.event_type == "buyer_requirement")
    assert rejection_event.occurred_at <= requirement_event.occurred_at


def test_carolina_has_an_active_property_interest_and_negotiation_activity(db_session: Session):
    """Carolina: active property interest exists, negotiation activity exists."""
    org = run_seed(db_session)
    context = _context(db_session, org.id, "carolina-reyes")

    assert any(pi.status == "negotiation" for pi in context.property_interests)
    assert any(a.activity_type == "negotiation" for a in context.activities)


def test_sergio_requirement_history_remains_relevant_and_is_not_lost(db_session: Session):
    """Sergio: previous requirement/history exists, current requirement remains relevant (not lost when it changed)."""
    org = run_seed(db_session)
    context = _context(db_session, org.id, "sergio-navarro")

    assert len(context.buyer_requirements) >= 2, "the old (changed) requirement must still be visible alongside the new one"
    statuses = {br.status for br in context.buyer_requirements}
    assert "cancelled" in statuses
    assert "active" in statuses
