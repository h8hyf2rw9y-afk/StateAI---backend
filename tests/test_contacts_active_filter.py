"""
GET /contacts?active=... — the "Clientes activos" view. A contact is active
when it has an open Opportunity (stage not won/lost) or a live Buyer
Requirement (status not cancelled/fulfilled); see
app/repositories/contact_repo.py's active_contact_condition for the single
definition and for why "owns an active Property" is not a criterion (no
Property -> Contact link exists in the data model).
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import Organization, User
from app.schemas.user import CurrentUser

CONTACTS = "/api/v1/contacts"


def _contact(client: TestClient, first_name: str) -> str:
    response = client.post(
        CONTACTS,
        json={"first_name": first_name, "last_name": "Prueba", "phone": f"+52 81 {uuid.uuid4().int % 10**8:08d}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _opportunity(client: TestClient, contact_id: str, stage: str = "qualification", **extra) -> str:
    response = client.post(
        f"{CONTACTS}/{contact_id}/opportunities",
        json={"opportunity_type": "buy", "title": "Compra", "stage": stage, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _requirement(client: TestClient, contact_id: str, status: str = "active") -> str:
    response = client.post(f"{CONTACTS}/{contact_id}/buyer-requirements", json={"property_type": "house"})
    assert response.status_code == 201, response.text
    requirement_id = response.json()["id"]
    if status != "active":
        patched = client.patch(f"/api/v1/buyer-requirements/{requirement_id}", json={"status": status})
        assert patched.status_code == 200, patched.text
    return requirement_id


def _names(client: TestClient, **params) -> list[str]:
    response = client.get(CONTACTS, params=params)
    assert response.status_code == 200, response.text
    return sorted(c["first_name"] for c in response.json())


def test_contacts_without_the_filter_are_unchanged(client: TestClient):
    _contact(client, "Sinrelaciones")
    with_opp = _contact(client, "ConOportunidad")
    _opportunity(client, with_opp)

    # Exactly the original behavior: every contact, active or not.
    assert _names(client) == ["ConOportunidad", "Sinrelaciones"]
    assert _names(client, limit=1, offset=0) != []


def test_a_contact_with_an_open_opportunity_is_active(client: TestClient):
    contact = _contact(client, "Abierta")
    _opportunity(client, contact, stage="negotiation")
    _contact(client, "Historico")

    assert _names(client, active=True) == ["Abierta"]


def test_every_non_terminal_stage_counts_as_open(client: TestClient):
    for stage in ("qualification", "search", "property_selected", "showing", "offer", "negotiation", "reservation", "contract", "closing"):
        contact = _contact(client, f"E-{stage}")
        _opportunity(client, contact, stage=stage)

    assert len(_names(client, active=True)) == 9


def test_a_won_opportunity_does_not_make_a_contact_active(client: TestClient):
    contact = _contact(client, "Ganada")
    _opportunity(client, contact, stage="won")

    assert _names(client, active=True) == []


def test_a_lost_opportunity_does_not_make_a_contact_active(client: TestClient):
    contact = _contact(client, "Perdida")
    _opportunity(client, contact, stage="lost", lost_reason="price")

    assert _names(client, active=True) == []


def test_closing_the_only_open_opportunity_deactivates_the_contact(client: TestClient):
    contact = _contact(client, "Cierra")
    opportunity = _opportunity(client, contact, stage="negotiation")
    assert _names(client, active=True) == ["Cierra"]

    client.patch(f"/api/v1/opportunities/{opportunity}", json={"stage": "won"})

    assert _names(client, active=True) == []


def test_one_open_opportunity_is_enough_even_next_to_closed_ones(client: TestClient):
    contact = _contact(client, "Mixta")
    _opportunity(client, contact, stage="won")
    _opportunity(client, contact, stage="lost", lost_reason="price")
    _opportunity(client, contact, stage="showing")

    assert _names(client, active=True) == ["Mixta"]


def test_a_live_buyer_requirement_makes_a_contact_active(client: TestClient):
    contact = _contact(client, "Buscando")
    _requirement(client, contact, status="active")
    _contact(client, "Nada")

    assert _names(client, active=True) == ["Buscando"]


def test_a_paused_requirement_still_counts_as_live(client: TestClient):
    contact = _contact(client, "Pausada")
    _requirement(client, contact, status="paused")

    assert _names(client, active=True) == ["Pausada"]


def test_cancelled_and_fulfilled_requirements_do_not_make_a_contact_active(client: TestClient):
    cancelled = _contact(client, "Cancelada")
    _requirement(client, cancelled, status="cancelled")
    fulfilled = _contact(client, "Cumplida")
    _requirement(client, fulfilled, status="fulfilled")

    assert _names(client, active=True) == []


def test_a_historical_contact_with_only_closed_relations_is_not_active(client: TestClient):
    contact = _contact(client, "Historica")
    _opportunity(client, contact, stage="won")
    _requirement(client, contact, status="fulfilled")

    assert _names(client, active=True) == []
    assert _names(client, active=False) == ["Historica"]


def test_both_relations_together_do_not_duplicate_the_contact(client: TestClient):
    contact = _contact(client, "Ambas")
    _opportunity(client, contact)
    _opportunity(client, contact, stage="offer")
    _requirement(client, contact)
    _requirement(client, contact)

    assert client.get(CONTACTS, params={"active": True}).json().__len__() == 1


def test_active_false_returns_the_complement(client: TestClient):
    active = _contact(client, "Activa")
    _opportunity(client, active)
    _contact(client, "Inactiva")

    everyone = set(_names(client))
    assert set(_names(client, active=True)) | set(_names(client, active=False)) == everyone
    assert set(_names(client, active=True)) & set(_names(client, active=False)) == set()
    assert _names(client, active=False) == ["Inactiva"]


def test_active_filter_keeps_pagination_and_the_roles_payload(client: TestClient):
    for i in range(3):
        contact = _contact(client, f"Act{i}")
        _opportunity(client, contact)
    first = client.get(CONTACTS, params={"active": True}).json()[0]
    client.post(f"{CONTACTS}/{first['id']}/roles", json={"role_key": "buyer"})

    page = client.get(CONTACTS, params={"active": True, "limit": 2}).json()

    assert len(page) == 2
    assert client.get(CONTACTS, params={"active": True, "limit": 2, "offset": 2}).json().__len__() == 1
    with_roles = next(c for c in client.get(CONTACTS, params={"active": True}).json() if c["id"] == first["id"])
    assert [r["role_key"] for r in with_roles["roles"]] == ["buyer"]


def test_active_rejects_a_non_boolean_value(client: TestClient):
    assert client.get(CONTACTS, params={"active": "maybe"}).status_code == 422


def test_active_view_never_leaks_another_organizations_contacts(db_session: Session):
    org_a, org_b = Organization(name="A"), Organization(name="B")
    db_session.add_all([org_a, org_b])
    db_session.flush()
    user_a = User(id=uuid.uuid4(), organization_id=org_a.id, role="owner")
    user_b = User(id=uuid.uuid4(), organization_id=org_b.id, role="owner")
    db_session.add_all([user_a, user_b])
    db_session.commit()
    cu_a = CurrentUser(id=user_a.id, email="a@x.com", organization_id=org_a.id, role="owner", provider="email")
    cu_b = CurrentUser(id=user_b.id, email="b@x.com", organization_id=org_b.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    try:
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_org_user] = lambda: cu_b
        client_b = TestClient(app)
        contact_b = _contact(client_b, "SoloB")
        _opportunity(client_b, contact_b)
        _requirement(client_b, contact_b)

        app.dependency_overrides[get_current_org_user] = lambda: cu_a
        assert TestClient(app).get(CONTACTS, params={"active": True}).json() == []
    finally:
        app.dependency_overrides.clear()


def test_active_filter_is_a_single_query_regardless_of_how_many_relations_exist(
    client: TestClient, db_session: Session
):
    """No N+1: the EXISTS checks run inside the one contacts SELECT (plus the one selectinload for roles), not per contact."""
    for i in range(6):
        contact = _contact(client, f"N{i}")
        _opportunity(client, contact)
        _requirement(client, contact)

    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(CONTACTS, params={"active": True})
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(response.json()) == 6
    contact_selects = [s for s in statements if "FROM contacts" in s]
    assert len(contact_selects) == 1
    assert contact_selects[0].count("EXISTS") == 2
    # One SELECT for contacts + one for roles (selectinload) + auth/user lookups happen outside the DB session override.
    assert len(statements) <= 3
