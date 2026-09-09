"""
Appointments (app/models/appointment.py): CRUD, lifecycle, invalid
cross-org references, and organization isolation.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import Organization, User
from app.schemas.user import CurrentUser


def _create_contact(client: TestClient) -> dict:
    return client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()


def _appointment_payload(**overrides) -> dict:
    fields = {
        "title": "Visita Casa Cumbres",
        "appointment_type": "showing",
        "start_at": "2026-09-15T16:00:00Z",
        "end_at": "2026-09-15T17:00:00Z",
    }
    fields.update(overrides)
    return fields


def test_create_and_get_appointment(client: TestClient, current_user: CurrentUser):
    response = client.post("/api/v1/appointments", json=_appointment_payload())
    assert response.status_code == 201
    appointment = response.json()
    assert appointment["title"] == "Visita Casa Cumbres"
    assert appointment["status"] == "scheduled"
    assert appointment["created_by_user_id"] == str(current_user.id)

    fetched = client.get(f"/api/v1/appointments/{appointment['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == appointment["id"]


def test_appointment_rejects_end_before_start(client: TestClient):
    response = client.post(
        "/api/v1/appointments",
        json=_appointment_payload(start_at="2026-09-15T17:00:00Z", end_at="2026-09-15T16:00:00Z"),
    )
    assert response.status_code == 422


def test_appointment_associated_with_a_contact(client: TestClient):
    contact = _create_contact(client)
    appointment = client.post("/api/v1/appointments", json=_appointment_payload(contact_id=contact["id"])).json()
    assert appointment["contact_id"] == contact["id"]

    listed = client.get("/api/v1/appointments", params={"contact_id": contact["id"]}).json()
    assert [a["id"] for a in listed] == [appointment["id"]]


def test_create_appointment_with_a_nonexistent_contact_is_404(client: TestClient):
    response = client.post("/api/v1/appointments", json=_appointment_payload(contact_id=str(uuid.uuid4())))
    assert response.status_code == 404


def test_create_appointment_with_a_nonexistent_property_is_404(client: TestClient):
    response = client.post("/api/v1/appointments", json=_appointment_payload(property_id=str(uuid.uuid4())))
    assert response.status_code == 404


def test_update_appointment_lifecycle(client: TestClient):
    appointment = client.post("/api/v1/appointments", json=_appointment_payload()).json()

    confirmed = client.patch(f"/api/v1/appointments/{appointment['id']}", json={"status": "confirmed"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    completed = client.patch(f"/api/v1/appointments/{appointment['id']}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_update_appointment_rejects_end_before_start_on_the_merged_row(client: TestClient):
    appointment = client.post(
        "/api/v1/appointments", json=_appointment_payload(start_at="2026-09-15T10:00:00Z", end_at="2026-09-15T11:00:00Z")
    ).json()

    response = client.patch(f"/api/v1/appointments/{appointment['id']}", json={"start_at": "2026-09-15T12:00:00Z"})
    assert response.status_code == 422


def test_delete_appointment(client: TestClient):
    appointment = client.post("/api/v1/appointments", json=_appointment_payload()).json()

    deleted = client.delete(f"/api/v1/appointments/{appointment['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/appointments/{appointment['id']}").status_code == 404


def test_list_appointments_filters_by_status(client: TestClient):
    scheduled = client.post("/api/v1/appointments", json=_appointment_payload(title="Scheduled")).json()
    other = client.post("/api/v1/appointments", json=_appointment_payload(title="Cancelled")).json()
    client.patch(f"/api/v1/appointments/{other['id']}", json={"status": "cancelled"})

    listed = client.get("/api/v1/appointments", params={"status": "scheduled"}).json()
    assert [a["id"] for a in listed] == [scheduled["id"]]


def test_appointments_are_isolated_by_organization(db_session: Session):
    """A user in org A must not be able to read, list, update, or delete org B's appointments."""
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
        appointment_b = client_b.post("/api/v1/appointments", json=_appointment_payload()).json()
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        assert client_a.get(f"/api/v1/appointments/{appointment_b['id']}").status_code == 404
        assert client_a.get("/api/v1/appointments").json() == []
        assert client_a.patch(f"/api/v1/appointments/{appointment_b['id']}", json={"status": "confirmed"}).status_code == 404
        assert client_a.delete(f"/api/v1/appointments/{appointment_b['id']}").status_code == 404
    finally:
        app.dependency_overrides.clear()
