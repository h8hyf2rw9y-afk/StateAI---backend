"""
Representative CRUD integration test — exercises the full stack (route ->
service -> repository -> SQLite) for Contacts. The other entities
(properties, buyer_requirements, property_interests) follow the exact same
pattern and aren't each re-tested exhaustively here.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.schemas.user import CurrentUser


def test_create_and_get_contact(client: TestClient):
    response = client.post(
        "/api/v1/contacts",
        json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"},
    )
    assert response.status_code == 201
    contact = response.json()
    assert contact["first_name"] == "Juan"
    assert contact["roles"] == []

    fetched = client.get(f"/api/v1/contacts/{contact['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == contact["id"]


def test_create_contact_without_email_or_phone_is_rejected(client: TestClient):
    response = client.post("/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez"})
    assert response.status_code == 422


def test_get_nonexistent_contact_is_404(client: TestClient):
    response = client.get(f"/api/v1/contacts/{uuid.uuid4()}")
    assert response.status_code == 404


def test_update_contact_patches_only_given_fields(client: TestClient):
    created = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()

    updated = client.patch(f"/api/v1/contacts/{created['id']}", json={"notes": "Interested in San Pedro"})
    assert updated.status_code == 200
    body = updated.json()
    assert body["notes"] == "Interested in San Pedro"
    assert body["first_name"] == "Juan"  # untouched


def test_assign_and_remove_contact_role(client: TestClient):
    created = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()

    assigned = client.post(f"/api/v1/contacts/{created['id']}/roles", json={"role_key": "buyer"})
    assert assigned.status_code == 200
    assert [r["role_key"] for r in assigned.json()["roles"]] == ["buyer"]

    removed = client.delete(f"/api/v1/contacts/{created['id']}/roles/buyer")
    assert removed.status_code == 200
    assert removed.json()["roles"] == []


def test_delete_contact(client: TestClient, current_user: CurrentUser):
    created = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()

    # Deleting a contact is a destructive operation restricted to owner/admin
    # (see require_role in app/core/security.py and README's Authorization
    # Model) — the shared `client`/`current_user` fixtures default to
    # "agent", so this test acts as an owner for the delete call itself.
    # test_delete_contact_is_forbidden_for_an_agent below covers the denial.
    owner = current_user.model_copy(update={"role": "owner"})
    app.dependency_overrides[get_current_org_user] = lambda: owner
    try:
        deleted = client.delete(f"/api/v1/contacts/{created['id']}")
    finally:
        app.dependency_overrides[get_current_org_user] = lambda: current_user
    assert deleted.status_code == 204

    assert client.get(f"/api/v1/contacts/{created['id']}").status_code == 404


def test_delete_contact_is_forbidden_for_an_agent(client: TestClient):
    """Contact deletion requires owner/admin — the default `client` fixture's role ("agent") must be denied."""
    created = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()

    response = client.delete(f"/api/v1/contacts/{created['id']}")
    assert response.status_code == 403

    # Untouched — the denied delete must not have gone through.
    assert client.get(f"/api/v1/contacts/{created['id']}").status_code == 200


def test_list_contacts_is_scoped_and_paginated(client: TestClient):
    for i in range(3):
        client.post("/api/v1/contacts", json={"first_name": f"Contact{i}", "last_name": "Test", "phone": f"+1{i}"})

    response = client.get("/api/v1/contacts", params={"limit": 2})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_missing_bearer_token_is_401(db_session):
    """
    Uses a bare TestClient (not the `client` fixture) so get_current_org_user
    is NOT overridden — this exercises the real 401 path, which short-circuits
    before ever needing network access to Supabase's JWKS endpoint.
    """

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/v1/contacts")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
