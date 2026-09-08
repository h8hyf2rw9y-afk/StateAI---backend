"""
Walks through the project brief's Use Cases 1-5 end to end: create a
contact, a property, a property interest (Case A), a buyer requirement
with a location and features (Case B), then confirm /matches finds the
property — and that a disqualifying must_have feature correctly excludes it.
"""

from fastapi.testclient import TestClient


def _create_matching_property(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/properties",
        json={
            "title": "Casa Valle Oriente",
            "property_type": "house",
            "status": "active",
            "price": 4_800_000,
            "city": "San Pedro Garza Garcia",
            "neighborhood": "Valle Oriente",
            "bedrooms": 3,
            "bathrooms": 2,
            "construction_m2": 220,
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_matching_requirement(client: TestClient, contact_id: str) -> dict:
    response = client.post(
        f"/api/v1/contacts/{contact_id}/buyer-requirements",
        json={
            "property_type": "house",
            "budget_min": 4_000_000,
            "budget_max": 5_000_000,
            "bedrooms_min": 3,
            "bathrooms_min": 2,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_matches_returns_qualifying_property(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()
    prop = _create_matching_property(client)
    requirement = _create_matching_requirement(client, contact["id"])

    client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/locations",
        json={"city": "San Pedro Garza Garcia", "neighborhood": "Valle Oriente"},
    )

    matches = client.get(f"/api/v1/buyer-requirements/{requirement['id']}/matches")
    assert matches.status_code == 200
    body = matches.json()
    assert len(body) == 1
    assert body[0]["property"]["id"] == prop["id"]


def test_matches_excludes_property_missing_a_must_have_feature(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()
    _create_matching_property(client)  # no "pool" feature assigned
    requirement = _create_matching_requirement(client, contact["id"])

    client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/features",
        json={"feature_key": "pool", "classification": "must_have"},
    )

    matches = client.get(f"/api/v1/buyer-requirements/{requirement['id']}/matches")
    assert matches.status_code == 200
    assert matches.json() == []


def test_matches_excludes_property_out_of_budget(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()
    client.post(
        "/api/v1/properties",
        json={
            "title": "Casa cara",
            "property_type": "house",
            "status": "active",
            "price": 9_000_000,  # above the requirement's budget_max
            "bedrooms": 3,
            "bathrooms": 2,
        },
    )
    requirement = _create_matching_requirement(client, contact["id"])

    matches = client.get(f"/api/v1/buyer-requirements/{requirement['id']}/matches")
    assert matches.status_code == 200
    assert matches.json() == []
