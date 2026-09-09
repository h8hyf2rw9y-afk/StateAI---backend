"""
Opportunities (app/models/opportunity.py): BUY/SELL creation, retrieval,
listing with filters, generic updates, stage changes (including the
Activity + Audit Log side effects), closing won/lost, reopening,
validation, and organization isolation. Entirely offline — no LLM/Ollama
involved anywhere in this file.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import Organization, User
from app.schemas.user import CurrentUser


def _create_contact(client: TestClient, **overrides) -> dict:
    fields = {"first_name": "Alejandro", "last_name": "Torres", "phone": "+52 811 000 0001"}
    fields.update(overrides)
    return client.post("/api/v1/contacts", json=fields).json()


def _create_property(client: TestClient, **overrides) -> dict:
    fields = {"title": "Casa Cumbres", "property_type": "house", "status": "active", "price": 5800000}
    fields.update(overrides)
    return client.post("/api/v1/properties", json=fields).json()


def _create_buyer_requirement(client: TestClient, contact_id: str, **overrides) -> dict:
    fields = {"property_type": "house"}
    fields.update(overrides)
    return client.post(f"/api/v1/contacts/{contact_id}/buyer-requirements", json=fields).json()


def _sell_payload(**overrides) -> dict:
    fields = {"opportunity_type": "sell", "title": "Sell Casa Cumbres"}
    fields.update(overrides)
    return fields


def _buy_payload(**overrides) -> dict:
    fields = {"opportunity_type": "buy", "title": "Buy search for Alejandro"}
    fields.update(overrides)
    return fields


# ---------------------------------------------------------------------------
# 1-2. Create BUY / SELL
# ---------------------------------------------------------------------------


def test_create_sell_opportunity(client: TestClient, current_user: CurrentUser):
    contact = _create_contact(client)
    prop = _create_property(client)

    response = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities",
        json=_sell_payload(property_id=prop["id"]),
    )
    assert response.status_code == 201
    opportunity = response.json()
    assert opportunity["opportunity_type"] == "sell"
    assert opportunity["contact_id"] == contact["id"]
    assert opportunity["property_id"] == prop["id"]
    assert opportunity["buyer_requirement_id"] is None
    assert opportunity["stage"] == "qualification"  # default
    assert opportunity["owner_user_id"] == str(current_user.id)  # defaults to creator
    assert opportunity["created_by_user_id"] == str(current_user.id)
    assert opportunity["closed_at"] is None


def test_create_buy_opportunity(client: TestClient):
    contact = _create_contact(client)
    requirement = _create_buyer_requirement(client, contact["id"])

    response = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities",
        json=_buy_payload(buyer_requirement_id=requirement["id"]),
    )
    assert response.status_code == 201
    opportunity = response.json()
    assert opportunity["opportunity_type"] == "buy"
    assert opportunity["buyer_requirement_id"] == requirement["id"]
    assert opportunity["property_id"] is None


def test_create_opportunity_without_property_or_buyer_requirement_is_allowed(client: TestClient):
    """Neither relationship is hard-required — an opportunity can start at pure qualification before a property/requirement is pinned down. See OpportunityService's docstring."""
    contact = _create_contact(client)
    response = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload())
    assert response.status_code == 201
    assert response.json()["stage"] == "qualification"


def test_create_opportunity_for_a_nonexistent_contact_is_404(client: TestClient):
    response = client.post(f"/api/v1/contacts/{uuid.uuid4()}/opportunities", json=_buy_payload())
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 3-4. Retrieve / list
# ---------------------------------------------------------------------------


def test_get_opportunity_by_id(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    fetched = client.get(f"/api/v1/opportunities/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_get_nonexistent_opportunity_is_404(client: TestClient):
    assert client.get(f"/api/v1/opportunities/{uuid.uuid4()}").status_code == 404


def test_list_opportunities_for_a_contact(client: TestClient):
    contact = _create_contact(client)
    other_contact = _create_contact(client, first_name="Sofía", last_name="Martínez", phone="+52 811 000 0002")
    mine = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()
    client.post(f"/api/v1/contacts/{other_contact['id']}/opportunities", json=_buy_payload())

    listed = client.get(f"/api/v1/contacts/{contact['id']}/opportunities").json()
    assert [o["id"] for o in listed] == [mine["id"]]


def test_list_opportunities_filters_by_type_and_stage(client: TestClient):
    contact = _create_contact(client)
    buy = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()
    sell = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_sell_payload()).json()
    client.patch(f"/api/v1/opportunities/{sell['id']}", json={"stage": "listing"})

    only_buy = client.get("/api/v1/opportunities", params={"opportunity_type": "buy"}).json()
    assert [o["id"] for o in only_buy] == [buy["id"]]

    only_listing = client.get("/api/v1/opportunities", params={"stage": "listing"}).json()
    assert [o["id"] for o in only_listing] == [sell["id"]]


def test_list_opportunities_filters_by_is_closed(client: TestClient):
    contact = _create_contact(client)
    open_one = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()
    closed_one = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()
    client.patch(f"/api/v1/opportunities/{closed_one['id']}", json={"stage": "won"})

    open_list = client.get("/api/v1/opportunities", params={"is_closed": "false"}).json()
    assert [o["id"] for o in open_list] == [open_one["id"]]

    closed_list = client.get("/api/v1/opportunities", params={"is_closed": "true"}).json()
    assert [o["id"] for o in closed_list] == [closed_one["id"]]


def test_list_opportunities_filters_by_owner(client: TestClient, current_user: CurrentUser, db_session: Session):
    other_user = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(other_user)
    db_session.commit()

    contact = _create_contact(client)
    mine = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()
    client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities",
        json=_buy_payload(owner_user_id=str(other_user.id)),
    )

    listed = client.get("/api/v1/opportunities", params={"owner_user_id": str(current_user.id)}).json()
    assert [o["id"] for o in listed] == [mine["id"]]


# ---------------------------------------------------------------------------
# 5. Generic update
# ---------------------------------------------------------------------------


def test_update_opportunity_generic_fields(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    updated = client.patch(
        f"/api/v1/opportunities/{created['id']}",
        json={"title": "Updated title", "expected_value": 4500000, "probability": 40},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["title"] == "Updated title"
    assert float(body["expected_value"]) == 4500000
    assert body["probability"] == 40
    assert body["stage"] == "qualification"  # untouched


def test_generic_update_does_not_create_a_stage_change_activity(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    client.patch(f"/api/v1/opportunities/{created['id']}", json={"title": "New title"})

    activities = client.get(f"/api/v1/opportunities/{created['id']}/activities").json()
    assert activities == []


# ---------------------------------------------------------------------------
# 6-7-8. Stage changes: generic, won, lost
# ---------------------------------------------------------------------------


def test_change_stage_creates_an_activity_and_audit_log(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    updated = client.patch(f"/api/v1/opportunities/{created['id']}", json={"stage": "negotiation"})
    assert updated.status_code == 200
    assert updated.json()["stage"] == "negotiation"

    activities = client.get(f"/api/v1/opportunities/{created['id']}/activities").json()
    assert len(activities) == 1
    assert activities[0]["activity_type"] == "stage_change"
    assert activities[0]["opportunity_id"] == created["id"]
    assert activities[0]["contact_id"] == contact["id"]
    assert "Qualification" in activities[0]["notes"] and "Negotiation" in activities[0]["notes"]

    audit = client.get("/api/v1/audit-logs", params={"entity_type": "opportunity", "entity_id": created["id"]}).json()
    actions = [entry["action"] for entry in audit]
    assert "OPPORTUNITY_CREATED" in actions
    assert "OPPORTUNITY_STAGE_CHANGED" in actions


def test_close_won_opportunity_auto_stamps_closed_at(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()
    assert created["closed_at"] is None

    won = client.patch(f"/api/v1/opportunities/{created['id']}", json={"stage": "won"})
    assert won.status_code == 200
    assert won.json()["stage"] == "won"
    assert won.json()["closed_at"] is not None

    audit = client.get("/api/v1/audit-logs", params={"entity_type": "opportunity", "entity_id": created["id"]}).json()
    assert "OPPORTUNITY_WON" in [entry["action"] for entry in audit]


def test_mark_lost_requires_a_lost_reason(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    rejected = client.patch(f"/api/v1/opportunities/{created['id']}", json={"stage": "lost"})
    assert rejected.status_code == 422

    accepted = client.patch(
        f"/api/v1/opportunities/{created['id']}", json={"stage": "lost", "lost_reason": "price"}
    )
    assert accepted.status_code == 200
    assert accepted.json()["stage"] == "lost"
    assert accepted.json()["lost_reason"] == "price"
    assert accepted.json()["closed_at"] is not None

    audit = client.get("/api/v1/audit-logs", params={"entity_type": "opportunity", "entity_id": created["id"]}).json()
    assert "OPPORTUNITY_LOST" in [entry["action"] for entry in audit]


def test_reopen_a_lost_opportunity_clears_closed_at_and_lost_reason(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()
    client.patch(f"/api/v1/opportunities/{created['id']}", json={"stage": "lost", "lost_reason": "price"})

    reopened = client.patch(f"/api/v1/opportunities/{created['id']}", json={"stage": "negotiation"})
    assert reopened.status_code == 200
    assert reopened.json()["stage"] == "negotiation"
    assert reopened.json()["closed_at"] is None
    assert reopened.json()["lost_reason"] is None

    audit = client.get("/api/v1/audit-logs", params={"entity_type": "opportunity", "entity_id": created["id"]}).json()
    assert "OPPORTUNITY_REOPENED" in [entry["action"] for entry in audit]


# ---------------------------------------------------------------------------
# 9. Validation of relationships
# ---------------------------------------------------------------------------


def test_buyer_requirement_belonging_to_another_contact_is_rejected(client: TestClient):
    contact = _create_contact(client)
    other_contact = _create_contact(client, first_name="Sofía", last_name="Martínez", phone="+52 811 000 0003")
    others_requirement = _create_buyer_requirement(client, other_contact["id"])

    response = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities",
        json=_buy_payload(buyer_requirement_id=others_requirement["id"]),
    )
    assert response.status_code == 422


def test_nonexistent_property_id_is_404(client: TestClient):
    contact = _create_contact(client)
    response = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities",
        json=_sell_payload(property_id=str(uuid.uuid4())),
    )
    assert response.status_code == 404


def test_sell_only_stage_rejected_for_a_buy_opportunity(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    response = client.patch(f"/api/v1/opportunities/{created['id']}", json={"stage": "listing"})
    assert response.status_code == 422


def test_buy_only_stage_rejected_for_a_sell_opportunity(client: TestClient):
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_sell_payload()).json()

    response = client.patch(f"/api/v1/opportunities/{created['id']}", json={"stage": "search"})
    assert response.status_code == 422


def test_opportunity_type_cannot_be_changed_after_creation(client: TestClient):
    """opportunity_type isn't even in OpportunityUpdate's schema — an extra field is silently ignored by Pydantic, not applied."""
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    updated = client.patch(f"/api/v1/opportunities/{created['id']}", json={"opportunity_type": "sell"})
    assert updated.status_code == 200
    assert updated.json()["opportunity_type"] == "buy"


# ---------------------------------------------------------------------------
# 10. Probability / expected_value validation
# ---------------------------------------------------------------------------


def test_probability_out_of_range_is_rejected(client: TestClient):
    contact = _create_contact(client)
    response = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload(probability=150)
    )
    assert response.status_code == 422


def test_negative_probability_is_rejected(client: TestClient):
    contact = _create_contact(client)
    response = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload(probability=-1))
    assert response.status_code == 422


def test_negative_expected_value_is_rejected(client: TestClient):
    contact = _create_contact(client)
    response = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload(expected_value=-100)
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 11-12. Organization isolation / unauthorized access
# ---------------------------------------------------------------------------


def test_opportunities_are_isolated_by_organization(db_session: Session):
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    user_b_row = User(id=uuid.uuid4(), organization_id=org_b.id, role="owner")
    db_session.add(user_b_row)
    db_session.commit()
    user_b = CurrentUser(id=user_b_row.id, email="b@example.com", organization_id=org_b.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_b
    try:
        client_b = TestClient(app)
        contact_b = _create_contact(client_b)
        opportunity_b = client_b.post(f"/api/v1/contacts/{contact_b['id']}/opportunities", json=_buy_payload()).json()
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        assert client_a.get(f"/api/v1/opportunities/{opportunity_b['id']}").status_code == 404
        assert client_a.get("/api/v1/opportunities").json() == []
        assert client_a.patch(f"/api/v1/opportunities/{opportunity_b['id']}", json={"stage": "won"}).status_code == 404
        # Cross-org contact_id also 404s before any opportunity is even considered.
        assert client_a.get(f"/api/v1/contacts/{contact_b['id']}/opportunities").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_unauthenticated_request_is_rejected():
    with TestClient(app) as unauthenticated_client:
        response = unauthenticated_client.get("/api/v1/opportunities")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 13. Role-based mutation — deliberately NOT gated (normal CRM operation,
# same as Task/Appointment) — see README's Authorization Model. This locks
# that decision in rather than leaving it undocumented/untested.
# ---------------------------------------------------------------------------


def test_agent_role_can_fully_manage_opportunities(client: TestClient):
    """The default `client` fixture's role is "agent" — opportunity create/update/stage-change must all work, unlike contact/property/etc. deletion."""
    contact = _create_contact(client)
    created = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload())
    assert created.status_code == 201

    updated = client.patch(f"/api/v1/opportunities/{created.json()['id']}", json={"stage": "won"})
    assert updated.status_code == 200


# ---------------------------------------------------------------------------
# 16. opportunity_id on Activities/Tasks/Appointments
# ---------------------------------------------------------------------------


def test_activity_can_reference_an_opportunity(client: TestClient):
    contact = _create_contact(client)
    opportunity = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    response = client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={"activity_type": "call", "occurred_at": "2026-09-01T10:00:00Z", "notes": "x", "opportunity_id": opportunity["id"]},
    )
    assert response.status_code == 201
    assert response.json()["opportunity_id"] == opportunity["id"]

    listed = client.get(f"/api/v1/opportunities/{opportunity['id']}/activities").json()
    assert len(listed) == 1
    assert listed[0]["activity_type"] == "call"


def test_activity_with_a_nonexistent_opportunity_id_is_404(client: TestClient):
    contact = _create_contact(client)
    response = client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={"activity_type": "call", "occurred_at": "2026-09-01T10:00:00Z", "notes": "x", "opportunity_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


def test_task_can_reference_and_be_filtered_by_opportunity(client: TestClient, current_user: CurrentUser):
    contact = _create_contact(client)
    opportunity = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_buy_payload()).json()

    task = client.post(
        "/api/v1/tasks",
        json={
            "assigned_to_user_id": str(current_user.id), "title": "Follow up", "task_type": "follow_up",
            "due_at": "2026-09-15T10:00:00Z", "opportunity_id": opportunity["id"],
        },
    )
    assert task.status_code == 201
    assert task.json()["opportunity_id"] == opportunity["id"]

    listed = client.get("/api/v1/tasks", params={"opportunity_id": opportunity["id"]}).json()
    assert [t["id"] for t in listed] == [task.json()["id"]]


def test_task_with_a_nonexistent_opportunity_id_is_404(client: TestClient, current_user: CurrentUser):
    response = client.post(
        "/api/v1/tasks",
        json={
            "assigned_to_user_id": str(current_user.id), "title": "Follow up", "task_type": "follow_up",
            "due_at": "2026-09-15T10:00:00Z", "opportunity_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404


def test_appointment_can_reference_and_be_filtered_by_opportunity(client: TestClient):
    contact = _create_contact(client)
    opportunity = client.post(f"/api/v1/contacts/{contact['id']}/opportunities", json=_sell_payload()).json()

    appointment = client.post(
        "/api/v1/appointments",
        json={
            "title": "Showing", "appointment_type": "showing",
            "start_at": "2026-09-15T16:00:00Z", "end_at": "2026-09-15T17:00:00Z",
            "opportunity_id": opportunity["id"],
        },
    )
    assert appointment.status_code == 201
    assert appointment.json()["opportunity_id"] == opportunity["id"]

    listed = client.get("/api/v1/appointments", params={"opportunity_id": opportunity["id"]}).json()
    assert [a["id"] for a in listed] == [appointment.json()["id"]]


def test_appointment_with_a_nonexistent_opportunity_id_is_404(client: TestClient):
    response = client.post(
        "/api/v1/appointments",
        json={
            "title": "Showing", "appointment_type": "showing",
            "start_at": "2026-09-15T16:00:00Z", "end_at": "2026-09-15T17:00:00Z",
            "opportunity_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404


def test_cross_organization_opportunity_id_is_rejected_on_task(db_session: Session):
    """A task in org A must not be able to link to org B's opportunity."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    user_b_row = User(id=uuid.uuid4(), organization_id=org_b.id, role="owner")
    db_session.add(user_b_row)
    db_session.commit()
    user_b = CurrentUser(id=user_b_row.id, email="b@example.com", organization_id=org_b.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_b
    try:
        client_b = TestClient(app)
        contact_b = _create_contact(client_b)
        opportunity_b = client_b.post(f"/api/v1/contacts/{contact_b['id']}/opportunities", json=_buy_payload()).json()
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        response = client_a.post(
            "/api/v1/tasks",
            json={
                "assigned_to_user_id": str(user_a.id), "title": "x", "task_type": "other",
                "due_at": "2026-09-15T10:00:00Z", "opportunity_id": opportunity_b["id"],
            },
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
