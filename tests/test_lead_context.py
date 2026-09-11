"""
The AI Context Layer: LeadContextService (Backend Service) and
get_lead_context (AI Tool) — see app/schemas/lead_context.py,
app/services/lead_context_service.py, app/ai/lead_context_tool.py.

Most scenarios call the service/tool directly (not through HTTP) since the
whole point of this layer is to be independently testable without a running
server or any agent framework — one HTTP-level smoke test at the bottom
covers the route itself.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.lead_context_tool import get_lead_context
from app.models.activity import Activity
from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact
from app.models.organization import Organization
from app.models.property import Property
from app.models.property_interest import PropertyInterest
from app.schemas.user import CurrentUser
from app.services.lead_context_service import LeadContextService
from scripts.seed_demo_data import det_id, run_seed


def _make_contact(db_session: Session, organization_id, **overrides) -> Contact:
    fields = {
        "organization_id": organization_id,
        "first_name": "Ana",
        "last_name": "Ramirez",
        "phone": "+52 81 5500 1234",
    }
    fields.update(overrides)
    contact = Contact(**fields)
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)
    return contact


def _make_property(db_session: Session, organization_id, **overrides) -> Property:
    fields = {
        "organization_id": organization_id,
        "title": "Casa Roble",
        "property_type": "house",
        "status": "active",
        "price": 4500000,
    }
    fields.update(overrides)
    prop = Property(**fields)
    db_session.add(prop)
    db_session.commit()
    db_session.refresh(prop)
    return prop


def _occurred(day_in_august_2026: int) -> datetime:
    return datetime(2026, 8, day_in_august_2026, 9, 0, tzinfo=timezone.utc)


def test_plain_contact_has_empty_lists_and_zero_engagement(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.contact.id == contact.id
    assert context.buyer_requirements == []
    assert context.property_interests == []
    assert context.properties == []
    assert context.activities == []
    assert context.timeline == []
    assert context.engagement_summary.activity_count == 0
    assert context.engagement_summary.last_activity_at is None
    assert context.engagement_summary.days_since_last_activity is None
    assert context.engagement_summary.has_active_buyer_requirement is False
    assert context.engagement_summary.active_property_interest_count == 0


def test_context_includes_buyer_requirement_with_locations_and_features(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    requirement = BuyerRequirement(
        organization_id=organization_id,
        contact_id=contact.id,
        status="active",
        property_type="apartment",
        budget_min=2000000,
        budget_max=3000000,
    )
    db_session.add(requirement)
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert len(context.buyer_requirements) == 1
    assert context.buyer_requirements[0].id == requirement.id
    assert context.buyer_requirements[0].budget_max == 3000000
    assert context.engagement_summary.has_active_buyer_requirement is True
    assert any(e.event_type == "buyer_requirement" for e in context.timeline)


def test_context_includes_property_interest_and_the_referenced_property(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    prop = _make_property(db_session, organization_id)
    interest = PropertyInterest(
        organization_id=organization_id, contact_id=contact.id, property_id=prop.id, status="interested"
    )
    db_session.add(interest)
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert len(context.property_interests) == 1
    assert context.property_interests[0].property_id == prop.id
    assert [p.id for p in context.properties] == [prop.id]
    assert context.engagement_summary.active_property_interest_count == 1
    assert any(e.event_type == "property_interest" for e in context.timeline)


def test_context_includes_activities_and_orders_the_timeline_chronologically(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    db_session.add_all(
        [
            Activity(
                organization_id=organization_id,
                contact_id=contact.id,
                activity_type="call",
                occurred_at=_occurred(20),
                notes="Segunda llamada",
            ),
            Activity(
                organization_id=organization_id,
                contact_id=contact.id,
                activity_type="note",
                occurred_at=_occurred(10),
                notes="Primer contacto",
            ),
        ]
    )
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.engagement_summary.activity_count == 2
    # SQLite round-trips DateTime(timezone=True) as naive (see
    # LeadContextService._engagement_summary's comment) — Postgres wouldn't
    # strip tzinfo here, so compare naive-to-naive rather than assert a
    # SQLite-only quirk as if it were the service's real contract.
    assert context.engagement_summary.last_activity_at.replace(tzinfo=None) == _occurred(20).replace(tzinfo=None)
    assert context.engagement_summary.days_since_last_activity is not None
    activity_events = [e for e in context.timeline if e.event_type == "activity"]
    assert [e.occurred_at for e in activity_events] == sorted(e.occurred_at for e in activity_events)
    assert activity_events[0].summary.startswith("note:")  # oldest first


def test_context_with_both_property_interest_and_buyer_requirement(db_session: Session, organization_id):
    """A contact can be in Case A (interested in a specific property) and Case B (also searching by criteria) at once."""
    contact = _make_contact(db_session, organization_id)
    prop = _make_property(db_session, organization_id)
    db_session.add_all(
        [
            PropertyInterest(organization_id=organization_id, contact_id=contact.id, property_id=prop.id, status="viewed"),
            BuyerRequirement(organization_id=organization_id, contact_id=contact.id, status="active", property_type="house"),
        ]
    )
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert len(context.property_interests) == 1
    assert len(context.buyer_requirements) == 1
    assert context.engagement_summary.has_active_buyer_requirement is True
    assert context.engagement_summary.active_property_interest_count == 1


def test_gabriela_transition_is_preserved_not_lost_or_duplicated(db_session: Session):
    """
    The Scenario A -> Scenario B transition from the demo data: Gabriela was
    rejected on a specific property (still visible, status=not_interested)
    and later opened a buyer requirement (status=active). Both must appear —
    the switch must not erase or duplicate her history.
    """
    org = run_seed(db_session)
    contact = db_session.get(Contact, det_id("contact:gabriela-ortiz"))

    context = LeadContextService(db_session).build(org.id, contact.id)

    assert len(context.property_interests) == 1
    assert context.property_interests[0].status == "not_interested"
    assert len(context.buyer_requirements) == 1
    assert context.buyer_requirements[0].status == "active"

    rejection_event = next(e for e in context.timeline if e.event_type == "property_interest")
    requirement_event = next(e for e in context.timeline if e.event_type == "buyer_requirement")
    assert rejection_event.occurred_at <= requirement_event.occurred_at


def test_get_lead_context_rejects_a_contact_from_another_organization(db_session: Session):
    """
    The AI tool must never let one organization's authenticated user reach
    another organization's contact, no matter what id is passed in — this is
    the concrete test of "never trust organization_id supplied by the AI".
    """
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.commit()

    contact_b = _make_contact(db_session, org_b.id, first_name="Ajeno", last_name="Contact")

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")

    with pytest.raises(HTTPException) as exc_info:
        get_lead_context(user_a, contact_b.id, db_session)
    assert exc_info.value.status_code == 404


def test_context_for_contact_with_partial_data_only_activities(db_session: Session, organization_id):
    """No buyer requirement, no property interest — only activity history. Every list must still be well-formed, not None."""
    contact = _make_contact(db_session, organization_id)
    db_session.add(
        Activity(
            organization_id=organization_id,
            contact_id=contact.id,
            activity_type="whatsapp",
            occurred_at=_occurred(5),
            notes="Primer mensaje",
        )
    )
    db_session.commit()

    context = LeadContextService(db_session).build(organization_id, contact.id)

    assert context.buyer_requirements == []
    assert context.property_interests == []
    assert context.properties == []
    assert len(context.activities) == 1
    assert len(context.timeline) == 1


def test_lead_context_is_deterministic_across_calls(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    prop = _make_property(db_session, organization_id)
    db_session.add_all(
        [
            PropertyInterest(organization_id=organization_id, contact_id=contact.id, property_id=prop.id, status="new"),
            Activity(
                organization_id=organization_id,
                contact_id=contact.id,
                activity_type="call",
                occurred_at=_occurred(3),
                notes="Llamada",
            ),
        ]
    )
    db_session.commit()

    service = LeadContextService(db_session)
    first = service.build(organization_id, contact.id)
    second = service.build(organization_id, contact.id)

    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(exclude={"generated_at"})


def test_context_fingerprint_is_stable_when_nothing_changed(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    db_session.add(BuyerRequirement(organization_id=organization_id, contact_id=contact.id, property_type="house"))
    db_session.commit()

    service = LeadContextService(db_session)
    first = service.compute_context_fingerprint(organization_id, contact.id)
    second = service.compute_context_fingerprint(organization_id, contact.id)

    assert first == second
    assert first["buyer_requirements"]["count"] == 1


def test_context_fingerprint_changes_when_a_buyer_requirement_is_added(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    service = LeadContextService(db_session)
    before = service.compute_context_fingerprint(organization_id, contact.id)

    db_session.add(BuyerRequirement(organization_id=organization_id, contact_id=contact.id, property_type="house"))
    db_session.commit()

    after = service.compute_context_fingerprint(organization_id, contact.id)
    assert before != after
    assert before["buyer_requirements"]["count"] == 0
    assert after["buyer_requirements"]["count"] == 1


def test_context_fingerprint_changes_when_an_existing_buyer_requirement_is_updated(db_session: Session, organization_id):
    """
    Forces `updated_at` forward explicitly (rather than relying on a plain
    field edit + commit) because SQLite's func.now() — unlike Postgres's —
    only has one-second resolution, and this test can otherwise run fast
    enough that "before" and "after" land in the same second; the fingerprint
    logic itself (comparing whatever updated_at value is present) is what's
    under test here, not the database's own onupdate timing.
    """
    contact = _make_contact(db_session, organization_id)
    requirement = BuyerRequirement(organization_id=organization_id, contact_id=contact.id, property_type="house")
    db_session.add(requirement)
    db_session.commit()

    service = LeadContextService(db_session)
    before = service.compute_context_fingerprint(organization_id, contact.id)

    requirement.status = "on_hold"
    requirement.updated_at = datetime.now(timezone.utc) + timedelta(days=1)
    db_session.commit()

    after = service.compute_context_fingerprint(organization_id, contact.id)
    assert before != after
    assert before["buyer_requirements"]["count"] == after["buyer_requirements"]["count"] == 1


def test_context_fingerprint_is_unaffected_by_a_different_contacts_data(db_session: Session, organization_id):
    contact = _make_contact(db_session, organization_id)
    other_contact = _make_contact(db_session, organization_id, first_name="Otro", last_name="Cliente")
    service = LeadContextService(db_session)
    before = service.compute_context_fingerprint(organization_id, contact.id)

    db_session.add(BuyerRequirement(organization_id=organization_id, contact_id=other_contact.id, property_type="house"))
    db_session.commit()

    after = service.compute_context_fingerprint(organization_id, contact.id)
    assert before == after


def test_lead_context_route_returns_the_structured_context(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Diego", "last_name": "Salas", "phone": "+52 81 5500 4321"}
    ).json()

    response = client.get(f"/api/v1/ai/lead-context/{contact['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["contact"]["id"] == contact["id"]
    assert body["buyer_requirements"] == []
    assert "engagement_summary" in body
