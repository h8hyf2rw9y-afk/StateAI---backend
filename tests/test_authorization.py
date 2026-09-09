"""
Role authorization (app/core/security.py's require_role/require_any_role):
the dependency's own grant/deny logic, plus the routes it's actually
applied to today — deleting a Contact, Property, Buyer Requirement, or
Property Interest, all restricted to owner/admin. See the README's
Authorization Model section for why nothing else is gated yet.
"""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.security import require_any_role, require_role
from app.schemas.user import CurrentUser


def _user(role: str) -> CurrentUser:
    return CurrentUser(id=uuid.uuid4(), email="x@example.com", organization_id=uuid.uuid4(), role=role, provider="email")


# --- require_role as a plain function (no HTTP/route plumbing needed) ------


def test_require_role_allows_a_listed_role():
    dependency = require_role("owner", "admin")
    result = dependency(current_user=_user("admin"))
    assert result.role == "admin"


def test_require_role_denies_an_unlisted_role():
    dependency = require_role("owner", "admin")
    with pytest.raises(HTTPException) as exc_info:
        dependency(current_user=_user("agent"))
    assert exc_info.value.status_code == 403


def test_require_role_with_a_single_role():
    dependency = require_role("owner")
    with pytest.raises(HTTPException):
        dependency(current_user=_user("admin"))
    assert dependency(current_user=_user("owner")).role == "owner"


def test_require_any_role_is_the_same_mechanism():
    assert require_any_role is require_role


# --- Applied to the real routes: delete on Contact/Property/BuyerRequirement/PropertyInterest ---


def _create_contact(client: TestClient) -> dict:
    return client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()


def test_delete_property_is_forbidden_for_an_agent_and_allowed_for_an_owner(client: TestClient, current_user):
    from app.core.security import get_current_org_user
    from app.main import app

    prop = client.post(
        "/api/v1/properties",
        json={"title": "Casa Cumbres", "property_type": "house", "status": "active", "price": 5800000},
    ).json()

    denied = client.delete(f"/api/v1/properties/{prop['id']}")
    assert denied.status_code == 403

    owner = current_user.model_copy(update={"role": "owner"})
    app.dependency_overrides[get_current_org_user] = lambda: owner
    try:
        allowed = client.delete(f"/api/v1/properties/{prop['id']}")
    finally:
        app.dependency_overrides[get_current_org_user] = lambda: current_user
    assert allowed.status_code == 204


def test_delete_buyer_requirement_is_forbidden_for_an_agent(client: TestClient):
    contact = _create_contact(client)
    requirement = client.post(
        f"/api/v1/contacts/{contact['id']}/buyer-requirements", json={"property_type": "house"}
    ).json()

    response = client.delete(f"/api/v1/buyer-requirements/{requirement['id']}")
    assert response.status_code == 403
    assert client.get(f"/api/v1/buyer-requirements/{requirement['id']}").status_code == 200


def test_delete_property_interest_is_forbidden_for_an_agent(client: TestClient):
    contact = _create_contact(client)
    prop = client.post(
        "/api/v1/properties",
        json={"title": "Casa Cumbres", "property_type": "house", "status": "active", "price": 5800000},
    ).json()
    interest = client.post(
        f"/api/v1/contacts/{contact['id']}/property-interests", json={"property_id": prop["id"]}
    ).json()

    response = client.delete(f"/api/v1/property-interests/{interest['id']}")
    assert response.status_code == 403
