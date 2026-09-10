"""
Activities/Interactions: creation, retrieval, contact timeline, property-
scoped list, validation, and organization isolation.
"""

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.activity import Activity
from app.models.contact import Contact
from app.models.organization import Organization
from app.schemas.user import CurrentUser


def _create_contact(client: TestClient) -> dict:
    return client.post(
        "/api/v1/contacts", json={"first_name": "Carlos", "last_name": "Mendoza", "phone": "+52 81 5500 0011"}
    ).json()


def _create_property(client: TestClient) -> dict:
    return client.post(
        "/api/v1/properties",
        json={"title": "Casa Cumbres", "property_type": "house", "status": "active", "price": 5800000},
    ).json()


def test_create_and_get_activity(client: TestClient):
    contact = _create_contact(client)

    response = client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={
            "activity_type": "call",
            "direction": "outbound",
            "occurred_at": "2026-08-25T10:00:00Z",
            "notes": "Llamada inicial, interesado en Casa Cumbres.",
        },
    )
    assert response.status_code == 201
    activity = response.json()
    assert activity["contact_id"] == contact["id"]
    assert activity["property_id"] is None
    assert activity["created_by_user_id"] is not None  # set from the authenticated caller

    fetched = client.get(f"/api/v1/activities/{activity['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["notes"] == "Llamada inicial, interesado en Casa Cumbres."


def test_create_activity_for_nonexistent_contact_is_404(client: TestClient):
    response = client.post(
        f"/api/v1/contacts/{uuid.uuid4()}/activities",
        json={"activity_type": "call", "occurred_at": "2026-08-25T10:00:00Z", "notes": "x"},
    )
    assert response.status_code == 404


def test_create_activity_with_invalid_type_is_422(client: TestClient):
    contact = _create_contact(client)
    response = client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={"activity_type": "carrier_pigeon", "occurred_at": "2026-08-25T10:00:00Z", "notes": "x"},
    )
    assert response.status_code == 422


def test_create_activity_with_nonexistent_property_is_404(client: TestClient):
    contact = _create_contact(client)
    response = client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={
            "activity_type": "property_viewing",
            "property_id": str(uuid.uuid4()),
            "occurred_at": "2026-08-25T10:00:00Z",
            "notes": "x",
        },
    )
    assert response.status_code == 404


def test_contact_timeline_is_chronological_oldest_first(client: TestClient):
    contact = _create_contact(client)

    for i, (occurred, note) in enumerate(
        [
            ("2026-08-10T09:00:00Z", "Contacto inicial"),
            ("2026-08-20T09:00:00Z", "Primera visita"),
            ("2026-08-14T09:00:00Z", "Seguimiento"),  # deliberately out of insertion order
        ]
    ):
        client.post(
            f"/api/v1/contacts/{contact['id']}/activities",
            json={"activity_type": "note", "occurred_at": occurred, "notes": note},
        )

    timeline = client.get(f"/api/v1/contacts/{contact['id']}/activities").json()
    assert [a["notes"] for a in timeline] == ["Contacto inicial", "Seguimiento", "Primera visita"]


def test_contact_timeline_filters_by_activity_type(client: TestClient):
    contact = _create_contact(client)
    client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={"activity_type": "call", "occurred_at": "2026-08-10T09:00:00Z", "notes": "Llamada"},
    )
    client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={"activity_type": "property_viewing", "occurred_at": "2026-08-11T09:00:00Z", "notes": "Visita"},
    )

    calls_only = client.get(f"/api/v1/contacts/{contact['id']}/activities", params={"activity_type": "call"}).json()
    assert len(calls_only) == 1
    assert calls_only[0]["activity_type"] == "call"


def test_property_activity_list(client: TestClient):
    contact = _create_contact(client)
    prop = _create_property(client)

    client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={
            "activity_type": "property_viewing",
            "property_id": prop["id"],
            "occurred_at": "2026-08-20T09:00:00Z",
            "notes": "Visitó la propiedad.",
        },
    )
    client.post(
        f"/api/v1/contacts/{contact['id']}/activities",
        json={"activity_type": "call", "occurred_at": "2026-08-21T09:00:00Z", "notes": "Sin propiedad asociada."},
    )

    property_activities = client.get(f"/api/v1/properties/{prop['id']}/activities").json()
    assert len(property_activities) == 1
    assert property_activities[0]["property_id"] == prop["id"]


def test_list_recent_activities_spans_every_contact(client: TestClient):
    """The org-wide feed (Dashboard's "Recent activity") isn't scoped to one contact — added for the CRM Integration Gaps task."""
    contact_a = _create_contact(client)
    contact_b = client.post(
        "/api/v1/contacts", json={"first_name": "Ana", "last_name": "Reyes", "email": "ana.reyes@example.com"}
    ).json()

    client.post(
        f"/api/v1/contacts/{contact_a['id']}/activities",
        json={"activity_type": "call", "occurred_at": "2026-08-25T10:00:00Z", "notes": "Llamada con Carlos."},
    )
    client.post(
        f"/api/v1/contacts/{contact_b['id']}/activities",
        json={"activity_type": "note", "occurred_at": "2026-08-25T11:00:00Z", "notes": "Nota sobre Ana."},
    )

    recent = client.get("/api/v1/activities").json()
    contact_ids = {a["contact_id"] for a in recent}
    assert contact_a["id"] in contact_ids
    assert contact_b["id"] in contact_ids


def test_list_recent_activities_respects_limit(client: TestClient):
    contact = _create_contact(client)
    for i in range(5):
        client.post(
            f"/api/v1/contacts/{contact['id']}/activities",
            json={"activity_type": "note", "occurred_at": f"2026-08-{10 + i:02d}T09:00:00Z", "notes": f"Nota {i}"},
        )

    limited = client.get("/api/v1/activities", params={"limit": 2}).json()
    assert len(limited) == 2


def test_list_recent_activities_missing_bearer_token_is_401(db_session: Session):
    """Uses a bare TestClient (not the `client` fixture) so get_current_org_user is NOT overridden — exercises the real 401 path."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/v1/activities")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_activities_are_isolated_by_organization(db_session: Session):
    """A user in org A must not be able to read or create activities against org B's contact."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    contact_b = Contact(organization_id=org_b.id, first_name="Ajeno", last_name="Contact", phone="+52 81 5500 0099")
    db_session.add(contact_b)
    db_session.commit()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        test_client = TestClient(app)

        # Org A can't create an activity against Org B's contact.
        create_response = test_client.post(
            f"/api/v1/contacts/{contact_b.id}/activities",
            json={"activity_type": "call", "occurred_at": "2026-08-20T09:00:00Z", "notes": "x"},
        )
        assert create_response.status_code == 404

        # Org A can't list Org B's contact's timeline either.
        list_response = test_client.get(f"/api/v1/contacts/{contact_b.id}/activities")
        assert list_response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_recent_activities_feed_is_isolated_by_organization(db_session: Session):
    """Org A's org-wide "recent activity" feed must never include Org B's activity, even though it's a plain list with no per-item ownership check to bypass."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    contact_b = Contact(organization_id=org_b.id, first_name="Ajeno", last_name="Contact", phone="+52 81 5500 0098")
    db_session.add(contact_b)
    db_session.flush()

    activity_b = Activity(
        organization_id=org_b.id,
        contact_id=contact_b.id,
        activity_type="note",
        occurred_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        notes="Nota de Org B — no debe ser visible para Org A.",
    )
    db_session.add(activity_b)
    db_session.commit()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        response = TestClient(app).get("/api/v1/activities")
        assert response.status_code == 200
        assert activity_b.notes not in [a["notes"] for a in response.json()]
    finally:
        app.dependency_overrides.clear()
