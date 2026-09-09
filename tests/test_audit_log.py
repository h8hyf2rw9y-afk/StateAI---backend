"""
The Audit Log (app/models/audit_log.py, app/services/audit_service.py):
record creation, actor tracking, before/after snapshots on update, deletion
records, and organization isolation.
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
    fields = {"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    fields.update(overrides)
    return client.post("/api/v1/contacts", json=fields).json()


def _audit_logs_for(client: TestClient, entity_type: str, entity_id: str) -> list[dict]:
    response = client.get("/api/v1/audit-logs", params={"entity_type": entity_type, "entity_id": entity_id})
    assert response.status_code == 200
    return response.json()


def test_creating_a_contact_writes_an_audit_record(client: TestClient):
    contact = _create_contact(client)

    logs = _audit_logs_for(client, "contact", contact["id"])
    assert len(logs) == 1
    assert logs[0]["action"] == "CONTACT_CREATED"
    assert logs[0]["entity_type"] == "contact"
    assert logs[0]["entity_id"] == contact["id"]
    assert logs[0]["before_data"] is None
    assert logs[0]["after_data"]["first_name"] == "Juan"


def test_actor_user_id_is_recorded(client: TestClient, current_user: CurrentUser):
    contact = _create_contact(client)

    logs = _audit_logs_for(client, "contact", contact["id"])
    assert logs[0]["actor_user_id"] == str(current_user.id)


def test_updating_a_contact_records_correct_before_and_after_values(client: TestClient):
    contact = _create_contact(client, notes="Old note")

    updated = client.patch(f"/api/v1/contacts/{contact['id']}", json={"notes": "New note"})
    assert updated.status_code == 200

    logs = _audit_logs_for(client, "contact", contact["id"])
    update_log = next(log for log in logs if log["action"] == "CONTACT_UPDATED")
    assert update_log["before_data"]["notes"] == "Old note"
    assert update_log["after_data"]["notes"] == "New note"
    # Untouched fields are identical in both snapshots — this wasn't a rewrite of the whole row.
    assert update_log["before_data"]["first_name"] == update_log["after_data"]["first_name"] == "Juan"


def test_deleting_a_contact_records_the_deletion_and_survives_the_contacts_own_removal(
    client: TestClient, current_user: CurrentUser
):
    contact = _create_contact(client)
    contact_id = contact["id"]

    owner = current_user.model_copy(update={"role": "owner"})
    app.dependency_overrides[get_current_org_user] = lambda: owner
    try:
        deleted = client.delete(f"/api/v1/contacts/{contact_id}")
    finally:
        app.dependency_overrides[get_current_org_user] = lambda: current_user
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/contacts/{contact_id}").status_code == 404

    # The audit trail outlives the contact it describes.
    logs = _audit_logs_for(client, "contact", contact_id)
    delete_log = next(log for log in logs if log["action"] == "CONTACT_DELETED")
    assert delete_log["before_data"]["id"] == contact_id
    assert delete_log["after_data"] is None


def test_property_buyer_requirement_and_activity_actions_are_logged(client: TestClient):
    prop = client.post(
        "/api/v1/properties",
        json={"title": "Casa Cumbres", "property_type": "house", "status": "active", "price": 5800000},
    ).json()
    assert _audit_logs_for(client, "property", prop["id"])[0]["action"] == "PROPERTY_CREATED"

    contact = _create_contact(client)
    requirement = client.post(
        f"/api/v1/contacts/{contact['id']}/buyer-requirements", json={"property_type": "house"}
    ).json()
    assert _audit_logs_for(client, "buyer_requirement", requirement["id"])[0]["action"] == "BUYER_REQUIREMENT_CREATED"

    activity = client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={"activity_type": "call", "occurred_at": "2026-08-25T10:00:00Z", "notes": "x"},
    ).json()
    assert _audit_logs_for(client, "activity", activity["id"])[0]["action"] == "ACTIVITY_CREATED"


def test_audit_logs_are_isolated_by_organization(db_session: Session):
    """A user in org A must not be able to list or fetch org B's audit log entries."""
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
        log_b_id = _audit_logs_for(client_b, "contact", contact_b["id"])[0]["id"]
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        # Org A's list never includes org B's entries, even unfiltered.
        assert client_a.get("/api/v1/audit-logs").json() == []
        # A direct fetch by id (guessed or leaked) also 404s.
        assert client_a.get(f"/api/v1/audit-logs/{log_b_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
