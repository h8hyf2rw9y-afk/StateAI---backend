"""
Property ownership/collaboration fields (ownership_type, external_source,
external_advisor_name, external_advisor_contact, collaboration_status) —
the "external/collaboration property" workflow: an advisor can represent a
property they don't own/manage themselves (found through another advisor
or an external portal) without duplicating it as a fake owned listing.
"""

import uuid

from fastapi.testclient import TestClient


def _create_property(client: TestClient, **overrides) -> dict:
    payload = {
        "title": "Casa Cumbres",
        "property_type": "house",
        "status": "active",
        "price": 5_800_000,
    }
    payload.update(overrides)
    response = client.post("/api/v1/properties", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_property_defaults_to_own_ownership(client: TestClient):
    """Every property created the normal way — including every one that existed before this field did — is "own" by default."""
    prop = _create_property(client)
    assert prop["ownership_type"] == "own"
    assert prop["external_source"] is None
    assert prop["collaboration_status"] is None


def test_can_create_an_external_collaboration_property(client: TestClient):
    prop = _create_property(
        client,
        title="Casa XYZ",
        ownership_type="external",
        external_source="Inmuebles24",
        external_advisor_name="Juan Pérez",
        external_advisor_contact="+52 81 1234 5678",
        collaboration_status="contacted",
    )
    assert prop["ownership_type"] == "external"
    assert prop["external_source"] == "Inmuebles24"
    assert prop["external_advisor_name"] == "Juan Pérez"
    assert prop["external_advisor_contact"] == "+52 81 1234 5678"
    assert prop["collaboration_status"] == "contacted"


def test_collaboration_status_on_an_own_property_is_rejected_at_creation(client: TestClient):
    response = client.post(
        "/api/v1/properties",
        json={
            "title": "Casa Cumbres",
            "property_type": "house",
            "ownership_type": "own",
            "collaboration_status": "contacted",
        },
    )
    assert response.status_code == 422


def test_collaboration_status_progresses_through_a_real_update(client: TestClient):
    prop = _create_property(client, title="Casa XYZ", ownership_type="external", collaboration_status="contacted")

    for status_ in ("info_requested", "info_received", "shared_with_client"):
        response = client.patch(f"/api/v1/properties/{prop['id']}", json={"collaboration_status": status_})
        assert response.status_code == 200
        assert response.json()["collaboration_status"] == status_


def test_collaboration_status_on_an_own_property_is_rejected_on_update(client: TestClient):
    prop = _create_property(client)
    response = client.patch(f"/api/v1/properties/{prop['id']}", json={"collaboration_status": "contacted"})
    assert response.status_code == 422


def test_switching_back_to_own_clears_the_external_fields(client: TestClient):
    """OrgScopedRepository.update() skips None values on a PATCH — switching ownership back to "own" must still actually clear the now-meaningless external/collaboration fields, not just leave them stale."""
    prop = _create_property(
        client,
        title="Casa XYZ",
        ownership_type="external",
        external_source="Inmuebles24",
        external_advisor_name="Juan Pérez",
        collaboration_status="contacted",
    )

    response = client.patch(f"/api/v1/properties/{prop['id']}", json={"ownership_type": "own"})
    assert response.status_code == 200
    body = response.json()
    assert body["ownership_type"] == "own"
    assert body["external_source"] is None
    assert body["external_advisor_name"] is None
    assert body["collaboration_status"] is None


def test_external_property_is_excluded_from_deterministic_matching(client: TestClient):
    """MatchingService only auto-ranks the advisor's own inventory — an external property was found for one specific client, not a general recommendation candidate."""
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Carlos", "last_name": "Hernandez", "phone": "+52 811 000 1111"}
    ).json()
    _create_property(
        client,
        title="Casa XYZ",
        ownership_type="external",
        price=6_500_000,
        status="active",
    )
    _create_property(client, title="Casa Cumbres", price=5_800_000, status="active")  # own, should still match

    requirement = client.post(
        f"/api/v1/contacts/{contact['id']}/buyer-requirements",
        json={"property_type": "house", "budget_min": 5_000_000, "budget_max": 7_000_000},
    ).json()

    matches = client.get(f"/api/v1/buyer-requirements/{requirement['id']}/matches").json()
    assert len(matches) == 1
    assert matches[0]["property"]["title"] == "Casa Cumbres"

    analysis = client.get(f"/api/v1/buyer-requirements/{requirement['id']}/property-matches").json()
    titles = [r["property"]["title"] for r in analysis]
    assert "Casa XYZ" not in titles
    assert "Casa Cumbres" in titles


def test_external_property_is_still_a_normal_property_for_everything_else(client: TestClient):
    """Not a parallel entity — an external property still works through the exact same Property/PropertyInterest/Opportunity architecture as an owned one."""
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Carlos", "last_name": "Hernandez", "phone": "+52 811 000 1111"}
    ).json()
    prop = _create_property(client, title="Casa XYZ", ownership_type="external")

    interest = client.post(
        f"/api/v1/contacts/{contact['id']}/property-interests", json={"property_id": prop["id"], "status": "new"}
    )
    assert interest.status_code == 201
    assert interest.json()["property_id"] == prop["id"]

    opportunity = client.post(
        f"/api/v1/contacts/{contact['id']}/opportunities",
        json={"opportunity_type": "buy", "property_id": prop["id"], "title": "Carlos x Casa XYZ", "stage": "showing"},
    )
    assert opportunity.status_code == 201
    assert opportunity.json()["property_id"] == prop["id"]

    # The opportunity is real, visible pipeline data — same list endpoint as any other.
    pipeline = client.get("/api/v1/opportunities").json()
    assert any(o["id"] == opportunity.json()["id"] for o in pipeline)


def test_property_ownership_fields_are_organization_isolated(db_session):
    """A cross-org read of an external property's collaboration details must 404, same as any other property field."""
    from app.core.database import get_db
    from app.core.security import get_current_org_user
    from app.main import app
    from app.models.organization import Organization, User
    from app.schemas.user import CurrentUser

    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()
    user_b_row = User(id=uuid.uuid4(), organization_id=org_b.id, role="owner")
    db_session.add(user_b_row)
    db_session.commit()

    def override_get_db():
        yield db_session

    user_b = CurrentUser(id=user_b_row.id, email="b@example.com", organization_id=org_b.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_b
    try:
        prop = _create_property(TestClient(app), title="Casa XYZ", ownership_type="external")
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        response = TestClient(app).get(f"/api/v1/properties/{prop['id']}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
