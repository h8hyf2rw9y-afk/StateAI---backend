"""
DELETE /buyer-requirements/{id}/locations/{location_id} and
DELETE /buyer-requirements/{id}/features/{feature_key}: removing one location or
one feature relationship without touching the requirement itself, the global
Feature catalog row, or another requirement's/organization's data.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.contact import Contact
from app.models.feature import Feature
from app.models.organization import Organization
from app.schemas.user import CurrentUser


def _create_contact(client: TestClient) -> dict:
    return client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()


def _create_requirement(client: TestClient, contact_id: str) -> dict:
    response = client.post(f"/api/v1/contacts/{contact_id}/buyer-requirements", json={"property_type": "house"})
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def test_remove_buyer_requirement_location(client: TestClient):
    contact = _create_contact(client)
    requirement = _create_requirement(client, contact["id"])

    added = client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/locations",
        json={"city": "San Pedro Garza Garcia", "neighborhood": "Valle Oriente"},
    )
    assert added.status_code == 200
    location_id = added.json()["locations"][0]["id"]

    removed = client.delete(f"/api/v1/buyer-requirements/{requirement['id']}/locations/{location_id}")
    assert removed.status_code == 200
    assert removed.json()["locations"] == []
    # The requirement itself is untouched, not deleted.
    assert removed.json()["id"] == requirement["id"]

    still_there = client.get(f"/api/v1/buyer-requirements/{requirement['id']}")
    assert still_there.status_code == 200
    assert still_there.json()["locations"] == []


def test_removing_a_location_belonging_to_another_requirement_is_a_noop(client: TestClient):
    contact = _create_contact(client)
    requirement_a = _create_requirement(client, contact["id"])
    requirement_b = _create_requirement(client, contact["id"])

    added = client.post(
        f"/api/v1/buyer-requirements/{requirement_a['id']}/locations",
        json={"city": "Monterrey"},
    )
    location_id = added.json()["locations"][0]["id"]

    # Attempting to delete requirement A's location via requirement B's path is a no-op.
    response = client.delete(f"/api/v1/buyer-requirements/{requirement_b['id']}/locations/{location_id}")
    assert response.status_code == 200
    assert response.json()["locations"] == []  # requirement B had none to begin with

    # Requirement A's location is still there, untouched.
    still_there = client.get(f"/api/v1/buyer-requirements/{requirement_a['id']}")
    assert len(still_there.json()["locations"]) == 1


def test_removing_a_location_unknown_id_is_a_noop(client: TestClient):
    contact = _create_contact(client)
    requirement = _create_requirement(client, contact["id"])

    response = client.delete(f"/api/v1/buyer-requirements/{requirement['id']}/locations/{uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json()["id"] == requirement["id"]


def test_removing_a_location_cross_organization_returns_404(db_session: Session):
    """A user in org A must not be able to delete org B's buyer requirement's location."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    contact_b = Contact(organization_id=org_b.id, first_name="Ajena", last_name="Contact", phone="+52 81 5500 0099")
    db_session.add(contact_b)
    db_session.commit()

    user_b = CurrentUser(id=uuid.uuid4(), email="b@example.com", organization_id=org_b.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_b
    try:
        client_b = TestClient(app)
        requirement_b = _create_requirement(client_b, str(contact_b.id))
        added = client_b.post(
            f"/api/v1/buyer-requirements/{requirement_b['id']}/locations",
            json={"city": "Monterrey"},
        )
        location_id = added.json()["locations"][0]["id"]
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        response = client_a.delete(f"/api/v1/buyer-requirements/{requirement_b['id']}/locations/{location_id}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


def test_remove_buyer_requirement_feature_deletes_relationship_not_catalog(client: TestClient, db_session: Session):
    contact = _create_contact(client)
    requirement = _create_requirement(client, contact["id"])

    added = client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/features",
        json={"feature_key": "pool", "classification": "must_have"},
    )
    assert added.status_code == 200
    assert [f["feature_key"] for f in added.json()["features"]] == ["pool"]

    removed = client.delete(f"/api/v1/buyer-requirements/{requirement['id']}/features/pool")
    assert removed.status_code == 200
    assert removed.json()["features"] == []
    assert removed.json()["id"] == requirement["id"]  # the requirement itself is untouched

    # The global Feature catalog row is untouched — only the relationship was deleted.
    assert db_session.get(Feature, "pool") is not None
    catalog = client.get("/api/v1/features").json()
    assert "pool" in {f["key"] for f in catalog}


def test_removing_a_feature_belonging_to_another_requirement_is_a_noop(client: TestClient):
    contact = _create_contact(client)
    requirement_a = _create_requirement(client, contact["id"])
    requirement_b = _create_requirement(client, contact["id"])

    client.post(
        f"/api/v1/buyer-requirements/{requirement_a['id']}/features",
        json={"feature_key": "pool", "classification": "preferred"},
    )

    response = client.delete(f"/api/v1/buyer-requirements/{requirement_b['id']}/features/pool")
    assert response.status_code == 200
    assert response.json()["features"] == []  # requirement B had none to begin with

    still_there = client.get(f"/api/v1/buyer-requirements/{requirement_a['id']}")
    assert [f["feature_key"] for f in still_there.json()["features"]] == ["pool"]


def test_removing_an_unknown_feature_key_is_a_noop(client: TestClient):
    contact = _create_contact(client)
    requirement = _create_requirement(client, contact["id"])

    response = client.delete(f"/api/v1/buyer-requirements/{requirement['id']}/features/does_not_exist")
    assert response.status_code == 200
    assert response.json()["id"] == requirement["id"]


# ---------------------------------------------------------------------------
# Duplicate protection (Task 5) — a unique index backs
# BuyerRequirementLocation.__table_args__ in app/models/buyer_requirement.py, but
# BuyerRequirementRepository.add_location upserts on (city, state, neighborhood)
# so a repeat submission updates the existing row's priority instead of hitting
# that index as a raw IntegrityError (mirrors add_feature's existing behavior).
# BuyerRequirementFeature's own duplicate protection is exercised indirectly by
# add_buyer_requirement_feature's upsert behavior in test_matching_api.py; it's
# enforced by an existing UniqueConstraint, not new work in this task.
# ---------------------------------------------------------------------------


def test_adding_the_same_location_twice_updates_it_instead_of_duplicating(client: TestClient):
    contact = _create_contact(client)
    requirement = _create_requirement(client, contact["id"])

    first = client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/locations",
        json={"city": "San Pedro Garza Garcia", "neighborhood": "Valle Oriente", "priority": 1},
    )
    assert first.status_code == 200
    location_id = first.json()["locations"][0]["id"]

    duplicate = client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/locations",
        json={"city": "San Pedro Garza Garcia", "neighborhood": "Valle Oriente", "priority": 2},
    )
    assert duplicate.status_code == 200

    unchanged = client.get(f"/api/v1/buyer-requirements/{requirement['id']}")
    locations = unchanged.json()["locations"]
    assert len(locations) == 1  # no duplicate row was created
    assert locations[0]["id"] == location_id  # same row, updated in place
    assert locations[0]["priority"] == 2


def test_removing_a_feature_cross_organization_returns_404(db_session: Session):
    """A user in org A must not be able to delete org B's buyer requirement's feature."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    contact_b = Contact(organization_id=org_b.id, first_name="Ajena", last_name="Contact", phone="+52 81 5500 0099")
    db_session.add(contact_b)
    db_session.commit()

    def override_get_db():
        yield db_session

    user_b = CurrentUser(id=uuid.uuid4(), email="b@example.com", organization_id=org_b.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_b
    try:
        client_b = TestClient(app)
        requirement_b = _create_requirement(client_b, str(contact_b.id))
        client_b.post(
            f"/api/v1/buyer-requirements/{requirement_b['id']}/features",
            json={"feature_key": "pool", "classification": "must_have"},
        )
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        response = client_a.delete(f"/api/v1/buyer-requirements/{requirement_b['id']}/features/pool")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
