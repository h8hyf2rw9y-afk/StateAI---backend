"""
Walks through the project brief's Use Cases 1-5 end to end: create a
contact, a property, a property interest (Case A), a buyer requirement
with a location and features (Case B), then confirm /matches finds the
property — and that a disqualifying must_have feature correctly excludes it.

GET .../property-matches (below the original /matches tests) is a
separate, richer analysis — see app/services/matching_service.py's
`analyze_matches` docstring for why it's not a replacement for /matches.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import Organization, User
from app.schemas.user import CurrentUser


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


# ---------------------------------------------------------------------------
# GET /buyer-requirements/{id}/property-matches — the richer, explainable
# analysis. Unlike /matches above, every active property gets a result
# (never silently excluded), classified match/partial_match/no_match with
# plain-English reasons — see app/services/matching_service.py.
# ---------------------------------------------------------------------------


def _create_contact(client: TestClient, name: str = "Juan") -> dict:
    response = client.post(
        "/api/v1/contacts", json={"first_name": name, "last_name": "Perez", "phone": "+52 811 000 0000"}
    )
    assert response.status_code == 201
    return response.json()


def _create_property(client: TestClient, **overrides) -> dict:
    payload = {
        "title": "Casa Valle Oriente",
        "property_type": "house",
        "status": "active",
        "price": 4_800_000,
        "currency": "MXN",
        "city": "San Pedro Garza Garcia",
        "state": "Nuevo Leon",
        "neighborhood": "Valle Oriente",
        "bedrooms": 3,
        "bathrooms": 2,
        "parking_spaces": 2,
        "construction_m2": 220,
        "land_m2": 300,
    }
    payload.update(overrides)
    response = client.post("/api/v1/properties", json=payload)
    assert response.status_code == 201
    return response.json()


def _create_requirement(client: TestClient, contact_id: str, **overrides) -> dict:
    payload = {
        "property_type": "house",
        "budget_min": 4_000_000,
        "budget_max": 5_000_000,
        "bedrooms_min": 3,
        "bathrooms_min": 2,
        "parking_spaces_min": 1,
        "construction_m2_min": 150,
        "land_m2_min": 200,
    }
    payload.update(overrides)
    response = client.post(f"/api/v1/contacts/{contact_id}/buyer-requirements", json=payload)
    assert response.status_code == 201
    return response.json()


def _get_analysis(client: TestClient, requirement_id: str) -> list[dict]:
    response = client.get(f"/api/v1/buyer-requirements/{requirement_id}/property-matches")
    assert response.status_code == 200
    return response.json()


def test_property_matches_classifies_a_fully_qualifying_property_as_match(client: TestClient):
    contact = _create_contact(client)
    prop = _create_property(client)
    requirement = _create_requirement(client, contact["id"])
    client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/locations",
        json={"city": "San Pedro Garza Garcia", "neighborhood": "Valle Oriente"},
    )

    results = _get_analysis(client, requirement["id"])
    assert len(results) == 1
    assert results[0]["property"]["id"] == prop["id"]
    assert results[0]["classification"] == "match"
    assert results[0]["criteria_unmet"] == []
    assert len(results[0]["criteria_met"]) > 0


def test_property_matches_flags_out_of_budget_property_as_unmet_not_excluded(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, price=9_000_000)  # above budget_max
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    assert len(results) == 1
    assert results[0]["classification"] == "partial_match"
    assert any("budget" in reason.lower() or "price" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_flags_property_below_budget_min_too(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, price=1_000_000)  # below budget_min
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    assert results[0]["classification"] == "partial_match"
    assert any("minimum budget" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_flags_currency_mismatch_as_unconfirmable(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, price=4_500_000, currency="USD")
    requirement = _create_requirement(client, contact["id"])  # requirement defaults to MXN

    results = _get_analysis(client, requirement["id"])
    assert any("currency" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_incompatible_type(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, property_type="apartment")
    requirement = _create_requirement(client, contact["id"])  # wants "house"

    results = _get_analysis(client, requirement["id"])
    assert any("property type" in reason.lower() for reason in results[0]["criteria_unmet"])
    assert results[0]["classification"] == "partial_match"


def test_property_matches_compatible_type(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, property_type="house")
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    assert any("property type matches" in reason.lower() for reason in results[0]["criteria_met"])


def test_property_matches_incompatible_city(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, city="Monterrey")
    requirement = _create_requirement(client, contact["id"])
    client.post(f"/api/v1/buyer-requirements/{requirement['id']}/locations", json={"city": "Guadalajara"})

    results = _get_analysis(client, requirement["id"])
    assert any("city" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_compatible_city(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, city="Guadalajara")
    requirement = _create_requirement(client, contact["id"])
    client.post(f"/api/v1/buyer-requirements/{requirement['id']}/locations", json={"city": "Guadalajara"})

    results = _get_analysis(client, requirement["id"])
    assert any("city matches" in reason.lower() for reason in results[0]["criteria_met"])


def test_property_matches_no_location_preference_skips_city_and_neighborhood_criteria(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, city="Anywhere", neighborhood="Anywhere Too")
    requirement = _create_requirement(client, contact["id"])  # no locations added at all

    results = _get_analysis(client, requirement["id"])
    joined = " ".join(results[0]["criteria_met"] + results[0]["criteria_unmet"]).lower()
    assert "city" not in joined
    assert "neighborhood" not in joined


def test_property_matches_bedrooms_below_minimum(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, bedrooms=1)
    requirement = _create_requirement(client, contact["id"])  # bedrooms_min=3

    results = _get_analysis(client, requirement["id"])
    assert any("bedrooms" in reason.lower() and "below" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_bedrooms_satisfies_minimum(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, bedrooms=4)
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    assert any("bedrooms" in reason.lower() for reason in results[0]["criteria_met"])


def test_property_matches_bathrooms_below_minimum(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, bathrooms=1)
    requirement = _create_requirement(client, contact["id"])  # bathrooms_min=2

    results = _get_analysis(client, requirement["id"])
    assert any("bathrooms" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_parking_below_minimum(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, parking_spaces=0)
    requirement = _create_requirement(client, contact["id"])  # parking_spaces_min=1

    results = _get_analysis(client, requirement["id"])
    assert any("parking" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_construction_area_below_minimum(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, construction_m2=50)
    requirement = _create_requirement(client, contact["id"])  # construction_m2_min=150

    results = _get_analysis(client, requirement["id"])
    assert any("construction area" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_land_area_below_minimum(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, land_m2=10)
    requirement = _create_requirement(client, contact["id"])  # land_m2_min=200

    results = _get_analysis(client, requirement["id"])
    assert any("land area" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_missing_must_have_feature_forces_no_match_regardless_of_other_criteria(client: TestClient):
    contact = _create_contact(client)
    prop = _create_property(client)  # perfectly matches every other criterion
    requirement = _create_requirement(client, contact["id"])
    client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/features",
        json={"feature_key": "pool", "classification": "must_have"},
    )

    results = _get_analysis(client, requirement["id"])
    assert len(results) == 1
    assert results[0]["property"]["id"] == prop["id"]
    assert results[0]["classification"] == "no_match"
    assert any("missing required feature: pool" in reason.lower() for reason in results[0]["criteria_unmet"])
    # Still transparent about what it DID satisfy, despite the hard override.
    assert len(results[0]["criteria_met"]) > 0


def test_property_matches_present_deal_breaker_feature_forces_no_match(client: TestClient):
    contact = _create_contact(client)
    prop = _create_property(client)
    client.post(f"/api/v1/properties/{prop['id']}/features", json={"feature_key": "elevator"})
    requirement = _create_requirement(client, contact["id"])
    client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/features",
        json={"feature_key": "elevator", "classification": "deal_breaker"},
    )

    results = _get_analysis(client, requirement["id"])
    assert results[0]["classification"] == "no_match"
    assert any("elevator" in reason.lower() for reason in results[0]["criteria_unmet"])


def test_property_matches_preferred_feature_present_and_missing_are_both_explained_individually(client: TestClient):
    contact = _create_contact(client)
    prop = _create_property(client)
    client.post(f"/api/v1/properties/{prop['id']}/features", json={"feature_key": "garden"})
    requirement = _create_requirement(client, contact["id"])
    client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/features",
        json={"feature_key": "garden", "classification": "preferred"},
    )
    client.post(
        f"/api/v1/buyer-requirements/{requirement['id']}/features",
        json={"feature_key": "pool", "classification": "preferred"},
    )

    results = _get_analysis(client, requirement["id"])
    assert any("garden" in reason.lower() for reason in results[0]["criteria_met"])
    assert any("pool" in reason.lower() for reason in results[0]["criteria_unmet"])
    # A missing *preferred* feature is a soft signal, not a hard override —
    # the property still classifies as a match if every other criterion holds.
    assert results[0]["classification"] == "partial_match"


def test_property_matches_multiple_properties_ranked_best_first(client: TestClient):
    contact = _create_contact(client)
    good = _create_property(client, title="Great fit")
    bad = _create_property(
        client,
        title="Poor fit",
        property_type="apartment",
        price=9_000_000,
        city="Nowhere",
        neighborhood="Nowhere Too",
        bedrooms=1,
        bathrooms=1,
        parking_spaces=0,
        construction_m2=10,
        land_m2=10,
    )
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    ids = [r["property"]["id"] for r in results]
    assert good["id"] in ids
    assert bad["id"] in ids
    assert ids.index(good["id"]) < ids.index(bad["id"])
    assert next(r for r in results if r["property"]["id"] == good["id"])["classification"] == "match"
    assert next(r for r in results if r["property"]["id"] == bad["id"])["classification"] == "no_match"


def test_property_matches_tie_between_equally_qualifying_properties_returns_both(client: TestClient):
    contact = _create_contact(client)
    first = _create_property(client, title="Twin A")
    second = _create_property(client, title="Twin B")
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    ids = {r["property"]["id"] for r in results}
    assert {first["id"], second["id"]} <= ids
    assert all(r["classification"] == "match" for r in results if r["property"]["id"] in {first["id"], second["id"]})


def test_property_matches_no_active_properties_returns_empty_list_not_an_error(client: TestClient):
    contact = _create_contact(client)
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    assert results == []


def test_property_matches_inactive_property_is_never_a_candidate(client: TestClient):
    contact = _create_contact(client)
    _create_property(client, status="draft")
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    assert results == []


def test_property_matches_nonexistent_buyer_requirement_is_404(client: TestClient):
    response = client.get(f"/api/v1/buyer-requirements/{uuid.uuid4()}/property-matches")
    assert response.status_code == 404


def test_property_matches_requirement_with_no_criteria_at_all_is_partial_match_not_fabricated(client: TestClient):
    """A requirement specifying nothing comparable can't honestly be called a match or a mismatch — see analyze_matches's own documented edge case."""
    contact = _create_contact(client)
    _create_property(client)
    response = client.post(f"/api/v1/contacts/{contact['id']}/buyer-requirements", json={})
    assert response.status_code == 201
    requirement = response.json()

    results = _get_analysis(client, requirement["id"])
    assert len(results) == 1
    assert results[0]["classification"] == "partial_match"
    assert results[0]["criteria_met"] == []
    assert results[0]["criteria_unmet"] == []


def test_property_matches_property_with_missing_optional_fields_is_unmet_not_confirmed(client: TestClient):
    """A property missing the data needed to confirm a criterion counts as unmet, same philosophy find_matches already established — never silently assumed to pass."""
    contact = _create_contact(client)
    _create_property(
        client,
        price=None,
        bedrooms=None,
        bathrooms=None,
        parking_spaces=None,
        construction_m2=None,
        land_m2=None,
    )
    requirement = _create_requirement(client, contact["id"])

    results = _get_analysis(client, requirement["id"])
    assert results[0]["classification"] == "partial_match"
    unmet_text = " ".join(results[0]["criteria_unmet"]).lower()
    assert "not on file" in unmet_text or "no listed price" in unmet_text


def test_property_matches_are_isolated_by_organization(db_session: Session):
    """A user in org A must not be able to read org B's buyer requirement's matches."""
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
        requirement_b = _create_requirement(client_b, contact_b["id"])
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        response = client_a.get(f"/api/v1/buyer-requirements/{requirement_b['id']}/property-matches")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_property_matches_missing_bearer_token_is_401(db_session):
    """Uses a bare TestClient (not the `client` fixture) so get_current_org_user is NOT overridden — exercises the real 401 path."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(f"/api/v1/buyer-requirements/{uuid.uuid4()}/property-matches")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
