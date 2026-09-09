"""
The AI Context Layer's Opportunity/Task/Appointment extension — see
app/schemas/lead_context.py, app/services/lead_context_service.py. Mirrors
tests/test_lead_context.py's own conventions exactly (most scenarios call
the service/tool directly, one HTTP-level smoke test at the bottom) since
this is an extension of that same layer, not a new one.

Real-data scenarios (Gabriela, Sergio, Carlos, Natalia) use the actual demo
seed built in the Opportunities task, exercised the same way
tests/test_golden_contacts.py already exercises Carlos/Gabriela/Carolina/
Sergio for the base LeadContext fields.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.lead_context_tool import get_lead_context
from app.models.activity import Activity
from app.models.appointment import Appointment
from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.organization import Organization
from app.models.property import Property
from app.models.task import Task
from app.schemas.user import CurrentUser
from app.services.lead_context_service import LeadContextService
from scripts.seed_demo_data import det_id, run_seed


def _make_contact(db_session: Session, organization_id, **overrides) -> Contact:
    fields = {"organization_id": organization_id, "first_name": "Ana", "last_name": "Ramirez", "phone": "+52 81 5500 1234"}
    fields.update(overrides)
    contact = Contact(**fields)
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)
    return contact


def _make_property(db_session: Session, organization_id, **overrides) -> Property:
    fields = {"organization_id": organization_id, "title": "Casa Roble", "property_type": "house", "status": "active", "price": 4500000}
    fields.update(overrides)
    prop = Property(**fields)
    db_session.add(prop)
    db_session.commit()
    db_session.refresh(prop)
    return prop


def _make_opportunity(db_session: Session, organization_id, contact_id, **overrides) -> Opportunity:
    fields = {
        "organization_id": organization_id, "contact_id": contact_id,
        "opportunity_type": "buy", "stage": "qualification", "title": "Test opportunity",
    }
    fields.update(overrides)
    opportunity = Opportunity(**fields)
    db_session.add(opportunity)
    db_session.commit()
    db_session.refresh(opportunity)
    return opportunity


def _in_days(n: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=n)


# --- 1-4: basic presence, types, multiplicity -------------------------------------------------


def test_contact_with_no_opportunities(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.opportunities == []
    assert context.tasks == []
    assert context.appointments == []
    assert context.engagement_summary.active_opportunity_count == 0
    assert context.engagement_summary.won_opportunity_count == 0
    assert context.engagement_summary.lost_opportunity_count == 0


def test_contact_with_one_buy_opportunity(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, opportunity_type="buy", stage="search")

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert len(context.opportunities) == 1
    assert context.opportunities[0].opportunity_type == "buy"
    assert context.opportunities[0].stage == "search"
    assert context.opportunities[0].contact_id == contact.id


def test_contact_with_one_sell_opportunity(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, opportunity_type="sell", stage="listing")

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert len(context.opportunities) == 1
    assert context.opportunities[0].opportunity_type == "sell"
    assert context.opportunities[0].stage == "listing"


def test_contact_with_multiple_opportunities_preserved_independently(db_session: Session, organization_id):
    """The exact 'do not merge, do not assume the newest is the only relevant one' domain rule."""
    contact = _make_contact(db_session, organization_id)
    lost = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="buy", stage="lost", lost_reason="price")
    active = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="buy", stage="negotiation")
    selling = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="sell", stage="listing")

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert len(context.opportunities) == 3
    ids = {o.id for o in context.opportunities}
    assert ids == {lost.id, active.id, selling.id}
    by_id = {o.id: o for o in context.opportunities}
    assert by_id[lost.id].stage == "lost"
    assert by_id[active.id].stage == "negotiation"
    assert by_id[selling.id].opportunity_type == "sell"


# --- 5-6: property / buyer requirement relationships ------------------------------------------


def test_opportunity_with_property(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    prop = _make_property(db_session, organization_id, title="Casa Cumbres", city="Monterrey")
    _make_opportunity(db_session, organization_id, contact.id, opportunity_type="sell", property_id=prop.id)

    context = LeadContextService(db_session).build(organization_id, contact.id)

    opp = context.opportunities[0]
    assert opp.property is not None
    assert opp.property.id == prop.id
    assert opp.property.title == "Casa Cumbres"
    assert opp.property.city == "Monterrey"
    # No duplication: the same property also appears once in the shared properties pool.
    assert [p.id for p in context.properties] == [prop.id]


def test_opportunity_with_buyer_requirement(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    requirement = BuyerRequirement(
        organization_id=organization_id, contact_id=contact.id, status="active",
        property_type="house", budget_min=4000000, budget_max=5000000,
    )
    db_session.add(requirement)
    db_session.commit()
    _make_opportunity(db_session, organization_id, contact.id, buyer_requirement_id=requirement.id)

    context = LeadContextService(db_session).build(organization_id, contact.id)

    opp = context.opportunities[0]
    assert opp.buyer_requirement is not None
    assert opp.buyer_requirement.id == requirement.id
    assert opp.buyer_requirement.budget_max == 5000000
    # Also fully present in the top-level buyer_requirements list — no need to duplicate it again here.
    assert [br.id for br in context.buyer_requirements] == [requirement.id]


def test_opportunity_without_property_or_buyer_requirement_has_none_summaries(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id)

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.opportunities[0].property is None
    assert context.opportunities[0].buyer_requirement is None


# --- 7-9: activities / tasks / appointments relationships --------------------------------------


def test_opportunity_with_activities(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id)
    activity = Activity(
        organization_id=organization_id, contact_id=contact.id, opportunity_id=opportunity.id,
        activity_type="stage_change", occurred_at=datetime.now(timezone.utc),
        notes="Opportunity stage changed from Qualification to Negotiation.",
    )
    db_session.add(activity)
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.opportunities[0].activity_ids == [activity.id]
    # Full detail lives once, in the top-level activities list — not duplicated per-opportunity.
    assert [a.id for a in context.activities] == [activity.id]
    assert context.activities[0].opportunity_id == opportunity.id


def test_opportunity_with_tasks(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id)
    task = Task(
        organization_id=organization_id, opportunity_id=opportunity.id,
        assigned_to_user_id=current_user.id, title="Follow up", task_type="follow_up",
        status="pending", priority="high", due_at=_in_days(2),
    )
    db_session.add(task)
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.opportunities[0].task_ids == [task.id]
    assert [t.id for t in context.tasks] == [task.id]
    assert context.tasks[0].opportunity_id == opportunity.id
    assert context.engagement_summary.pending_task_count == 1


def test_opportunity_with_appointments(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="sell")
    start = _in_days(3)
    appointment = Appointment(
        organization_id=organization_id, opportunity_id=opportunity.id, contact_id=contact.id,
        title="Showing", appointment_type="showing", status="confirmed", start_at=start, end_at=start + timedelta(hours=1),
    )
    db_session.add(appointment)
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.opportunities[0].appointment_ids == [appointment.id]
    assert [a.id for a in context.appointments] == [appointment.id]
    assert context.appointments[0].opportunity_id == opportunity.id
    assert context.engagement_summary.upcoming_appointment_count == 1


def test_task_linked_only_via_opportunity_still_appears(db_session: Session, organization_id, current_user):
    """A task about this contact's opportunity but with no contact_id of its own must still be found — see TaskRepository.list_for_contact."""
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id)
    task = Task(
        organization_id=organization_id, opportunity_id=opportunity.id, contact_id=None,
        assigned_to_user_id=current_user.id, title="No direct contact_id", task_type="other",
        status="pending", priority="medium", due_at=_in_days(1),
    )
    db_session.add(task)
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert [t.id for t in context.tasks] == [task.id]
    assert context.opportunities[0].task_ids == [task.id]


# --- 10-13: active / won / lost / multi-stage -----------------------------------------------


def test_active_opportunity_is_active_true(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, stage="negotiation")

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.opportunities[0].is_active is True
    assert context.engagement_summary.active_opportunity_count == 1


def test_won_opportunity(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, stage="won", closed_at=datetime.now(timezone.utc))

    context = LeadContextService(db_session).build(organization_id, contact.id)

    opp = context.opportunities[0]
    assert opp.stage == "won"
    assert opp.is_active is False
    assert opp.closed_at is not None
    assert context.engagement_summary.won_opportunity_count == 1
    assert context.engagement_summary.active_opportunity_count == 0


def test_lost_opportunity(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(
        db_session, organization_id, contact.id, stage="lost", lost_reason="chose_another_property",
        closed_at=datetime.now(timezone.utc),
    )

    context = LeadContextService(db_session).build(organization_id, contact.id)

    opp = context.opportunities[0]
    assert opp.stage == "lost"
    assert opp.is_active is False
    assert opp.lost_reason == "chose_another_property"
    assert context.engagement_summary.lost_opportunity_count == 1


def test_multiple_opportunities_with_different_stages_all_reflected(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, stage="won", closed_at=datetime.now(timezone.utc))
    _make_opportunity(
        db_session, organization_id, contact.id, stage="lost", lost_reason="price", closed_at=datetime.now(timezone.utc)
    )
    _make_opportunity(db_session, organization_id, contact.id, stage="showing")

    context = LeadContextService(db_session).build(organization_id, contact.id)

    stages = {o.stage for o in context.opportunities}
    assert stages == {"won", "lost", "showing"}
    assert context.engagement_summary.won_opportunity_count == 1
    assert context.engagement_summary.lost_opportunity_count == 1
    assert context.engagement_summary.active_opportunity_count == 1


# --- 14: timeline preservation ------------------------------------------------------------------


def test_timeline_includes_opportunity_creation_event(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="buy", stage="search")

    context = LeadContextService(db_session).build(organization_id, contact.id)

    opportunity_events = [e for e in context.timeline if e.event_type == "opportunity"]
    assert len(opportunity_events) == 1
    assert opportunity_events[0].related_id == opportunity.id
    assert "buy" in opportunity_events[0].summary and "search" in opportunity_events[0].summary


def test_timeline_reuses_stage_change_activities_not_a_second_history(db_session: Session, organization_id):
    """Stage changes must NOT get their own timeline event_type — they flow in as normal 'activity' events, same mechanism as any other Activity."""
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id)
    activity = Activity(
        organization_id=organization_id, contact_id=contact.id, opportunity_id=opportunity.id,
        activity_type="stage_change", occurred_at=datetime.now(timezone.utc),
        notes="Opportunity stage changed from Qualification to Negotiation.",
    )
    db_session.add(activity)
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    event_types = {e.event_type for e in context.timeline}
    assert "stage_change" not in event_types  # no separate history system
    stage_change_event = next(e for e in context.timeline if e.related_id == activity.id)
    assert stage_change_event.event_type == "activity"
    assert stage_change_event.summary.startswith("stage_change:")


def test_existing_timeline_event_types_unaffected(db_session: Session, organization_id):
    """Regression: buyer_requirement/property_interest/activity timeline events still work exactly as before."""
    contact = _make_contact(db_session, organization_id)
    prop = _make_property(db_session, organization_id)
    db_session.add_all(
        [
            BuyerRequirement(organization_id=organization_id, contact_id=contact.id, status="active", property_type="house"),
            Activity(
                organization_id=organization_id, contact_id=contact.id, activity_type="call",
                occurred_at=datetime.now(timezone.utc), notes="x",
            ),
        ]
    )
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    event_types = {e.event_type for e in context.timeline}
    assert "buyer_requirement" in event_types
    assert "activity" in event_types


# --- 15: engagement summary deterministic metrics -----------------------------------------------


def test_engagement_summary_pending_and_overdue_task_counts(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    db_session.add_all(
        [
            Task(
                organization_id=organization_id, contact_id=contact.id, assigned_to_user_id=current_user.id,
                title="Overdue", task_type="follow_up", status="pending", priority="high", due_at=_in_days(-3),
            ),
            Task(
                organization_id=organization_id, contact_id=contact.id, assigned_to_user_id=current_user.id,
                title="Not due yet", task_type="call", status="pending", priority="medium", due_at=_in_days(5),
            ),
            Task(
                organization_id=organization_id, contact_id=contact.id, assigned_to_user_id=current_user.id,
                title="Already done", task_type="call", status="completed", priority="low",
                due_at=_in_days(-10), completed_at=_in_days(-9),
            ),
        ]
    )
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.engagement_summary.pending_task_count == 2  # overdue + not-yet-due, not the completed one
    assert context.engagement_summary.overdue_task_count == 1


def test_engagement_summary_upcoming_appointment_count_excludes_past_and_cancelled(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    future_confirmed = _in_days(2)
    past = _in_days(-2)
    db_session.add_all(
        [
            Appointment(
                organization_id=organization_id, contact_id=contact.id, title="Upcoming", appointment_type="call",
                status="confirmed", start_at=future_confirmed, end_at=future_confirmed + timedelta(hours=1),
            ),
            Appointment(
                organization_id=organization_id, contact_id=contact.id, title="Already happened", appointment_type="call",
                status="completed", start_at=past, end_at=past + timedelta(hours=1),
            ),
            Appointment(
                organization_id=organization_id, contact_id=contact.id, title="Cancelled but future", appointment_type="call",
                status="cancelled", start_at=_in_days(3), end_at=_in_days(3) + timedelta(hours=1),
            ),
        ]
    )
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.engagement_summary.upcoming_appointment_count == 1


def test_engagement_summary_is_deterministic_aggregation_not_a_judgment(db_session: Session, organization_id):
    """No score/probability/classification field exists on EngagementSummary — only counts and dates."""
    contact = _make_contact(db_session, organization_id)
    context = LeadContextService(db_session).build(organization_id, contact.id)

    fields = set(type(context.engagement_summary).model_fields.keys())
    forbidden = {"score", "ai_score", "conversion_probability", "classification", "temperature", "prediction", "sentiment"}
    assert fields.isdisjoint(forbidden)


# --- 16: cross-organization isolation -----------------------------------------------------------


def test_opportunity_context_rejects_a_contact_from_another_organization(db_session: Session):
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.commit()

    contact_b = _make_contact(db_session, org_b.id, first_name="Ajeno", last_name="Contact")
    _make_opportunity(db_session, org_b.id, contact_b.id)

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")

    with pytest.raises(HTTPException) as exc_info:
        get_lead_context(user_a, contact_b.id, db_session)
    assert exc_info.value.status_code == 404


def test_opportunities_from_another_organization_never_leak_into_a_same_id_lookup(db_session: Session, organization_id):
    """Belt-and-suspenders: even if a contact existed in the caller's own org, opportunities/tasks/appointments queries are always organization_id-scoped, never global."""
    other_org = Organization(name="Other Org")
    db_session.add(other_org)
    db_session.commit()

    contact = _make_contact(db_session, organization_id)
    other_contact = _make_contact(db_session, other_org.id, first_name="Otro", last_name="Contacto")
    _make_opportunity(db_session, other_org.id, other_contact.id)

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.opportunities == []


# --- 17-18: partial data / determinism -----------------------------------------------------------


def test_partial_data_only_an_opportunity_no_other_entities(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id)

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.buyer_requirements == []
    assert context.property_interests == []
    assert context.activities == []
    assert context.tasks == []
    assert context.appointments == []
    assert len(context.opportunities) == 1


def test_lead_context_with_opportunities_is_deterministic_across_calls(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id, stage="negotiation")
    db_session.add(
        Task(
            organization_id=organization_id, opportunity_id=opportunity.id, assigned_to_user_id=current_user.id,
            title="x", task_type="other", status="pending", priority="medium", due_at=_in_days(1),
        )
    )
    db_session.commit()

    service = LeadContextService(db_session)
    first = service.build(organization_id, contact.id)
    second = service.build(organization_id, contact.id)

    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(exclude={"generated_at"})


# --- 19: HTTP route ---------------------------------------------------------------------------


def test_lead_context_route_includes_opportunities_tasks_and_appointments(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Diego", "last_name": "Salas", "phone": "+52 81 5500 4321"}
    ).json()
    opportunity = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities", json={"opportunity_type": "buy", "title": "Búsqueda"}
    ).json()

    response = client.get(f"/api/v1/ai/lead-context/{contact['id']}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["opportunities"]) == 1
    assert body["opportunities"][0]["id"] == opportunity["id"]
    assert body["tasks"] == []
    assert body["appointments"] == []
    assert "active_opportunity_count" in body["engagement_summary"]


def test_lead_context_route_accepts_task_and_appointment_limits(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Diego", "last_name": "Salas", "phone": "+52 81 5500 4322"}
    ).json()

    response = client.get(
        f"/api/v1/ai/lead-context/{contact['id']}", params={"task_limit": 5, "appointment_limit": 5}
    )
    assert response.status_code == 200


# --- 20: real demo-data validation ---------------------------------------------------------------


def test_gabriela_has_two_independent_opportunities_in_context(db_session: Session):
    """Gabriela: a lost opportunity (the property she rejected) and a separate active search — must both appear, never merged."""
    org = run_seed(db_session)
    contact = db_session.get(Contact, det_id("contact:gabriela-ortiz"))

    context = LeadContextService(db_session).build(org.id, contact.id)

    assert len(context.opportunities) == 2
    stages = {o.stage for o in context.opportunities}
    assert "lost" in stages
    assert "search" in stages
    lost_opp = next(o for o in context.opportunities if o.stage == "lost")
    assert lost_opp.lost_reason
    assert lost_opp.is_active is False


def test_sergio_has_a_won_opportunity_in_context(db_session: Session):
    org = run_seed(db_session)
    contact = db_session.get(Contact, det_id("contact:sergio-navarro"))

    context = LeadContextService(db_session).build(org.id, contact.id)

    won = [o for o in context.opportunities if o.stage == "won"]
    assert len(won) == 1
    assert won[0].closed_at is not None
    assert won[0].is_active is False


def test_carlos_has_an_overdue_task_reflected_in_engagement_summary(db_session: Session):
    org = run_seed(db_session)
    contact = db_session.get(Contact, det_id("contact:carlos-mendoza"))

    context = LeadContextService(db_session).build(org.id, contact.id)

    assert context.engagement_summary.overdue_task_count >= 1
    assert any(t.opportunity_id is not None for t in context.tasks)


def test_natalia_has_an_upcoming_appointment_reflected_in_engagement_summary(db_session: Session):
    org = run_seed(db_session)
    contact = db_session.get(Contact, det_id("contact:natalia-ramirez"))

    context = LeadContextService(db_session).build(org.id, contact.id)

    assert context.engagement_summary.upcoming_appointment_count >= 1
    assert any(a.opportunity_id is not None for a in context.appointments)


def test_paola_opportunity_has_linked_activity_history(db_session: Session):
    """The seed's 'meaningful activity history' scenario — several of Paola's existing activities are linked via opportunity_id."""
    org = run_seed(db_session)
    contact = db_session.get(Contact, det_id("contact:paola-rodriguez"))

    context = LeadContextService(db_session).build(org.id, contact.id)

    assert len(context.opportunities) == 1
    assert len(context.opportunities[0].activity_ids) >= 2
