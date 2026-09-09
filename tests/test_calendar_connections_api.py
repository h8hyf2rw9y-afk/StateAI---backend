"""
Calendar connections (app/models/calendar_connection.py): registering
intent to connect, personal ownership, re-connect upsert behavior, and
confirming no token field is ever present on the wire.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.user import CurrentUser


def test_create_calendar_connection(client: TestClient, current_user: CurrentUser):
    response = client.post("/api/v1/calendar-connections", json={"provider": "google"})
    assert response.status_code == 201
    connection = response.json()
    assert connection["provider"] == "google"
    assert connection["status"] == "pending"
    assert connection["user_id"] == str(current_user.id)
    # No token field is ever returned — see app/models/calendar_connection.py's docstring on why none exists.
    assert "access_token" not in connection
    assert "refresh_token" not in connection


def test_reconnecting_the_same_provider_returns_the_existing_connection(client: TestClient):
    first = client.post("/api/v1/calendar-connections", json={"provider": "google"}).json()
    second = client.post("/api/v1/calendar-connections", json={"provider": "google"}).json()
    assert second["id"] == first["id"]

    listed = client.get("/api/v1/calendar-connections").json()
    assert len(listed) == 1


def test_list_my_connections_only(client: TestClient, db_session: Session, current_user: CurrentUser):
    from app.models.organization import User

    other_user = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(other_user)
    db_session.commit()

    from app.repositories.calendar_connection_repo import CalendarConnectionRepository

    CalendarConnectionRepository(db_session).create(
        current_user.organization_id, user_id=other_user.id, provider="apple", status="pending"
    )
    db_session.commit()

    client.post("/api/v1/calendar-connections", json={"provider": "google"})

    listed = client.get("/api/v1/calendar-connections").json()
    assert [c["provider"] for c in listed] == ["google"]


def test_delete_calendar_connection(client: TestClient):
    connection = client.post("/api/v1/calendar-connections", json={"provider": "notion"}).json()

    deleted = client.delete(f"/api/v1/calendar-connections/{connection['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/calendar-connections").json() == []


def test_a_user_cannot_delete_another_users_connection(
    client: TestClient, db_session: Session, current_user: CurrentUser
):
    from app.models.organization import User
    from app.repositories.calendar_connection_repo import CalendarConnectionRepository

    other_user = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(other_user)
    db_session.commit()
    others_connection = CalendarConnectionRepository(db_session).create(
        current_user.organization_id, user_id=other_user.id, provider="apple", status="pending"
    )
    db_session.commit()

    response = client.delete(f"/api/v1/calendar-connections/{others_connection.id}")
    assert response.status_code == 404
