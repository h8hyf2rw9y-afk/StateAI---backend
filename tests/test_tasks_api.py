"""
Tasks (app/models/task.py): CRUD, contact/property association, completion,
due dates, invalid cross-org references, and organization isolation.
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


def _task_payload(current_user: CurrentUser, **overrides) -> dict:
    fields = {
        "assigned_to_user_id": str(current_user.id),
        "title": "Llamar a Juan",
        "task_type": "call",
        "due_at": "2026-09-15T10:00:00Z",
    }
    fields.update(overrides)
    return fields


def test_create_and_get_task(client: TestClient, current_user: CurrentUser):
    response = client.post("/api/v1/tasks", json=_task_payload(current_user))
    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Llamar a Juan"
    assert task["status"] == "pending"
    assert task["priority"] == "medium"  # default
    assert task["assigned_to_user_id"] == str(current_user.id)
    assert task["created_by_user_id"] == str(current_user.id)

    fetched = client.get(f"/api/v1/tasks/{task['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == task["id"]


def test_task_associated_with_a_contact(client: TestClient, current_user: CurrentUser):
    contact = _create_contact(client)
    task = client.post("/api/v1/tasks", json=_task_payload(current_user, contact_id=contact["id"])).json()
    assert task["contact_id"] == contact["id"]

    listed = client.get("/api/v1/tasks", params={"contact_id": contact["id"]}).json()
    assert [t["id"] for t in listed] == [task["id"]]


def test_task_associated_with_a_property(client: TestClient, current_user: CurrentUser):
    prop = client.post(
        "/api/v1/properties",
        json={"title": "Casa Cumbres", "property_type": "house", "status": "active", "price": 5800000},
    ).json()
    task = client.post(
        "/api/v1/tasks", json=_task_payload(current_user, property_id=prop["id"], task_type="document")
    ).json()
    assert task["property_id"] == prop["id"]

    listed = client.get("/api/v1/tasks", params={"property_id": prop["id"]}).json()
    assert [t["id"] for t in listed] == [task["id"]]


def test_create_task_with_a_nonexistent_contact_is_404(client: TestClient, current_user: CurrentUser):
    response = client.post("/api/v1/tasks", json=_task_payload(current_user, contact_id=str(uuid.uuid4())))
    assert response.status_code == 404


def test_create_task_with_a_nonexistent_property_is_404(client: TestClient, current_user: CurrentUser):
    response = client.post("/api/v1/tasks", json=_task_payload(current_user, property_id=str(uuid.uuid4())))
    assert response.status_code == 404


def test_update_task_fields(client: TestClient, current_user: CurrentUser):
    task = client.post("/api/v1/tasks", json=_task_payload(current_user)).json()

    updated = client.patch(f"/api/v1/tasks/{task['id']}", json={"priority": "urgent", "status": "in_progress"})
    assert updated.status_code == 200
    assert updated.json()["priority"] == "urgent"
    assert updated.json()["status"] == "in_progress"
    assert updated.json()["completed_at"] is None


def test_completing_a_task_auto_stamps_completed_at(client: TestClient, current_user: CurrentUser):
    task = client.post("/api/v1/tasks", json=_task_payload(current_user)).json()
    assert task["completed_at"] is None

    completed = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None


def test_completing_a_task_with_an_explicit_completed_at_is_not_overridden(client: TestClient, current_user: CurrentUser):
    task = client.post("/api/v1/tasks", json=_task_payload(current_user)).json()

    explicit_time = "2026-09-10T08:00:00Z"
    completed = client.patch(
        f"/api/v1/tasks/{task['id']}", json={"status": "completed", "completed_at": explicit_time}
    )
    assert completed.status_code == 200
    # SQLite (the test DB) drops tzinfo on round-trip even for a
    # DateTime(timezone=True) column, unlike real Postgres — compare
    # without the "Z" suffix, same reasoning as
    # LeadContextService._engagement_summary's comment on the same quirk.
    assert completed.json()["completed_at"].rstrip("Z") == explicit_time.rstrip("Z")


def test_due_date_is_returned_as_given(client: TestClient, current_user: CurrentUser):
    task = client.post("/api/v1/tasks", json=_task_payload(current_user, due_at="2026-12-01T09:00:00Z")).json()
    assert task["due_at"].rstrip("Z") == "2026-12-01T09:00:00"


def test_list_tasks_filters_by_status(client: TestClient, current_user: CurrentUser):
    pending = client.post("/api/v1/tasks", json=_task_payload(current_user, title="Pending task")).json()
    other = client.post("/api/v1/tasks", json=_task_payload(current_user, title="Done task")).json()
    client.patch(f"/api/v1/tasks/{other['id']}", json={"status": "completed"})

    listed = client.get("/api/v1/tasks", params={"status": "pending"}).json()
    assert [t["id"] for t in listed] == [pending["id"]]


def test_delete_task(client: TestClient, current_user: CurrentUser):
    task = client.post("/api/v1/tasks", json=_task_payload(current_user)).json()

    deleted = client.delete(f"/api/v1/tasks/{task['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404


def test_tasks_are_isolated_by_organization(db_session: Session):
    """A user in org A must not be able to read, list, update, or delete org B's tasks."""
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
        task_b = client_b.post("/api/v1/tasks", json=_task_payload(user_b)).json()
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        assert client_a.get(f"/api/v1/tasks/{task_b['id']}").status_code == 404
        assert client_a.get("/api/v1/tasks").json() == []
        assert client_a.patch(f"/api/v1/tasks/{task_b['id']}", json={"status": "completed"}).status_code == 404
        assert client_a.delete(f"/api/v1/tasks/{task_b['id']}").status_code == 404
    finally:
        app.dependency_overrides.clear()
