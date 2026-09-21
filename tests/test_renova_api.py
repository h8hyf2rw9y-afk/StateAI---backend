"""
Renova cases (app/models/renova_case.py, app/services/renova_case_service.py,
app/api/routes/renova.py) — the independent house-flipping evaluation
module. Sensitive-data behavior (NSS / credit number, audit exclusion, AI
isolation) lives in tests/test_renova_privacy.py; this file covers the CRUD
contract, validation, advisor rules, filters and organization isolation.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User
from app.schemas.user import CurrentUser

URL = "/api/v1/renova/cases"


def payload(user_id, **overrides) -> dict:
    body = {
        "assigned_user_id": str(user_id),
        "entry_date": "2026-09-20",
        "owner_name": "María López",
        "owner_phone": "+52 81 5555 0101",
    }
    body.update(overrides)
    return body


def _create(client: TestClient, user: CurrentUser, **overrides) -> dict:
    response = client.post(URL, json=payload(user.id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _audit_actions(db_session: Session, case_id: str) -> list[str]:
    rows = db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(case_id)).all()
    return sorted(r.action for r in rows)


# --- create / read -----------------------------------------------------------


def test_create_case_with_only_the_required_fields(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    assert case["owner_name"] == "María López"
    assert case["owner_phone"] == "+52 81 5555 0101"
    assert case["status"] == "new"
    assert case["source"] == "whatsapp"
    assert case["currency"] == "MXN"
    assert case["has_deeds"] == "unknown"
    assert case["assigned_user_id"] == str(current_user.id)
    assert case["created_by_user_id"] == str(current_user.id)
    assert case["organization_id"] == str(current_user.organization_id)
    # Everything that isn't captured yet stays empty rather than being invented.
    assert case["final_offer"] is None and case["market_value"] is None
    assert case["total_debt"] is None
    assert case["nss_masked"] is None and case["credit_number_masked"] is None


def test_create_case_with_every_section_filled(client: TestClient, current_user: CurrentUser):
    case = _create(
        client,
        current_user,
        marital_status="married_conjugal_partnership",
        spouse_name="Juan Pérez",
        spouse_phone="+52 81 5555 0202",
        dwelling_type="duplex",
        floors=2,
        bathrooms="2.5",
        bedrooms=3,
        conditions="Requiere pintura y cambio de cocina.",
        has_deeds="yes",
        deeds_holder_name="María López",
        final_offer="950000",
        market_value="1400000.50",
        property_tax_debt="12000",
        other_debt="3000",
        water_debt="800.25",
        electricity_debt="450",
        gas_debt="0",
        debt_owed_to="Infonavit",
        owner_expected_amount="1100000",
        sale_reason="Se muda de ciudad.",
        key_questions="¿Hay adeudos con el banco?",
        general_situation="Propietaria dispuesta a negociar.",
        notes="Contactar por la tarde.",
    )

    assert case["dwelling_type"] == "duplex"
    assert case["floors"] == 2 and case["bedrooms"] == 3
    assert Decimal(case["bathrooms"]) == Decimal("2.5")
    assert Decimal(case["market_value"]) == Decimal("1400000.50")
    assert case["spouse_name"] == "Juan Pérez"
    assert case["debt_owed_to"] == "Infonavit"


def test_get_case_detail(client: TestClient, current_user: CurrentUser):
    created = _create(client, current_user, notes="detalle")

    response = client.get(f"{URL}/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["notes"] == "detalle"


def test_unknown_case_is_404(client: TestClient):
    assert client.get(f"{URL}/{uuid.uuid4()}").status_code == 404
    assert client.patch(f"{URL}/{uuid.uuid4()}", json={"notes": "x"}).status_code == 404


def test_total_debt_is_derived_from_the_five_debt_fields(client: TestClient, current_user: CurrentUser):
    case = _create(
        client,
        current_user,
        property_tax_debt="12000",
        other_debt="3000.50",
        water_debt="800",
        electricity_debt="450",
        gas_debt="100",
        # Not part of the debt total:
        owner_expected_amount="999999",
        market_value="1400000",
    )

    assert Decimal(case["total_debt"]) == Decimal("16350.50")


def test_total_debt_counts_uncaptured_debts_as_zero_but_is_null_when_none_captured(
    client: TestClient, current_user: CurrentUser
):
    partial = _create(client, current_user, water_debt="500")
    assert Decimal(partial["total_debt"]) == Decimal("500")

    none_captured = _create(client, current_user)
    assert none_captured["total_debt"] is None


def test_total_debt_is_not_stored_as_a_column(db_session: Session):
    from app.models.renova_case import RenovaCase

    assert "total_debt" not in RenovaCase.__table__.columns


def test_money_keeps_decimal_precision(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, market_value="1234567.89")
    fetched = client.get(f"{URL}/{case['id']}").json()

    assert Decimal(fetched["market_value"]) == Decimal("1234567.89")


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "final_offer",
        "market_value",
        "property_tax_debt",
        "other_debt",
        "water_debt",
        "electricity_debt",
        "gas_debt",
        "owner_expected_amount",
    ],
)
def test_negative_money_is_rejected(client: TestClient, current_user: CurrentUser, field: str):
    response = client.post(URL, json=payload(current_user.id, **{field: "-1"}))

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["floors", "bathrooms", "bedrooms"])
def test_negative_counts_are_rejected(client: TestClient, current_user: CurrentUser, field: str):
    response = client.post(URL, json=payload(current_user.id, **{field: -1}))

    assert response.status_code == 422


def test_money_beyond_the_column_precision_is_rejected(client: TestClient, current_user: CurrentUser):
    assert client.post(URL, json=payload(current_user.id, market_value="1000000000000")).status_code == 422
    assert client.post(URL, json=payload(current_user.id, market_value="10.123")).status_code == 422


@pytest.mark.parametrize("missing", ["owner_name", "owner_phone", "entry_date", "assigned_user_id"])
def test_required_fields_are_enforced(client: TestClient, current_user: CurrentUser, missing: str):
    body = payload(current_user.id)
    del body[missing]

    assert client.post(URL, json=body).status_code == 422


def test_blank_required_text_is_rejected_and_blank_optional_text_becomes_null(
    client: TestClient, current_user: CurrentUser
):
    assert client.post(URL, json=payload(current_user.id, owner_name="   ")).status_code == 422

    case = _create(client, current_user, spouse_name="  ", notes="")
    assert case["spouse_name"] is None and case["notes"] is None


def test_long_text_is_capped(client: TestClient, current_user: CurrentUser):
    assert client.post(URL, json=payload(current_user.id, notes="x" * 5001)).status_code == 422
    assert client.post(URL, json=payload(current_user.id, owner_name="x" * 201)).status_code == 422


def test_invalid_enum_values_are_rejected(client: TestClient, current_user: CurrentUser):
    for field, value in (("status", "bogus"), ("dwelling_type", "castle"), ("has_deeds", "maybe"), ("source", "carrier_pigeon")):
        assert client.post(URL, json=payload(current_user.id, **{field: value})).status_code == 422


def test_spouse_and_financial_fields_are_optional(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)
    assert case["spouse_name"] is None and case["final_offer"] is None


# --- update / status / advisor -------------------------------------------------


def test_update_case_changes_only_the_fields_sent(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, notes="original", owner_expected_amount="900000")

    response = client.patch(f"{URL}/{case['id']}", json={"notes": "actualizado"})

    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == "actualizado"
    assert Decimal(body["owner_expected_amount"]) == Decimal("900000")
    assert body["owner_name"] == "María López"


def test_update_can_clear_an_optional_field_with_null(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, final_offer="500000")

    body = client.patch(f"{URL}/{case['id']}", json={"final_offer": None}).json()

    assert body["final_offer"] is None


def test_update_cannot_null_a_required_field(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    for field in ("owner_name", "owner_phone", "status", "entry_date", "assigned_user_id"):
        assert client.patch(f"{URL}/{case['id']}", json={field: None}).status_code == 422


def test_update_rejects_negative_amounts(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    assert client.patch(f"{URL}/{case['id']}", json={"water_debt": "-5"}).status_code == 422


def test_status_change_is_persisted_and_any_transition_is_allowed(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    for status in ("reviewing", "offer_sent", "reviewing", "cancelled"):
        response = client.patch(f"{URL}/{case['id']}", json={"status": status})
        assert response.status_code == 200
        assert response.json()["status"] == status
    assert client.get(f"{URL}/{case['id']}").json()["status"] == "cancelled"


def test_there_is_no_delete_endpoint(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    assert client.delete(f"{URL}/{case['id']}").status_code == 405
    assert client.get(f"{URL}/{case['id']}").status_code == 200


def test_reassigning_to_another_user_of_the_same_organization(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    colleague = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(colleague)
    db_session.commit()
    case = _create(client, current_user)

    response = client.patch(f"{URL}/{case['id']}", json={"assigned_user_id": str(colleague.id)})

    assert response.status_code == 200
    assert response.json()["assigned_user_id"] == str(colleague.id)


def _other_org_user(db_session: Session) -> User:
    other_org = Organization(name="Otra Inmobiliaria")
    db_session.add(other_org)
    db_session.flush()
    other_user = User(id=uuid.uuid4(), organization_id=other_org.id, role="agent")
    db_session.add(other_user)
    db_session.commit()
    return other_user


def test_cannot_create_a_case_assigned_to_an_advisor_of_another_organization(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    outsider = _other_org_user(db_session)

    response = client.post(URL, json=payload(outsider.id))

    assert response.status_code == 404
    assert client.get(URL).json() == []


def test_cannot_reassign_a_case_to_an_advisor_of_another_organization(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    outsider = _other_org_user(db_session)
    case = _create(client, current_user)

    response = client.patch(f"{URL}/{case['id']}", json={"assigned_user_id": str(outsider.id)})

    assert response.status_code == 404
    assert client.get(f"{URL}/{case['id']}").json()["assigned_user_id"] == str(current_user.id)


def test_cannot_assign_to_a_user_that_does_not_exist(client: TestClient, current_user: CurrentUser):
    assert client.post(URL, json=payload(uuid.uuid4())).status_code == 404


# --- audit ---------------------------------------------------------------------


def test_creating_a_case_is_audited(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create(client, current_user)

    assert _audit_actions(db_session, case["id"]) == ["RENOVA_CASE_CREATED"]
    row = db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(case["id"])).one()
    assert row.entity_type == "renova_case"
    assert row.actor_user_id == current_user.id
    assert row.organization_id == current_user.organization_id
    assert row.before_data is None and row.after_data["owner_name"] == "María López"


def test_editing_a_case_is_audited_with_before_and_after(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    case = _create(client, current_user, notes="antes")

    client.patch(f"{URL}/{case['id']}", json={"notes": "después"})

    assert _audit_actions(db_session, case["id"]) == ["RENOVA_CASE_CREATED", "RENOVA_CASE_UPDATED"]
    row = db_session.query(AuditLog).filter(AuditLog.action == "RENOVA_CASE_UPDATED").one()
    assert row.before_data["notes"] == "antes"
    assert row.after_data["notes"] == "después"


def test_status_assignee_and_financial_changes_each_get_their_own_audit_action(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    colleague = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(colleague)
    db_session.commit()
    case = _create(client, current_user)

    client.patch(f"{URL}/{case['id']}", json={"status": "reviewing"})
    client.patch(f"{URL}/{case['id']}", json={"assigned_user_id": str(colleague.id)})
    client.patch(f"{URL}/{case['id']}", json={"market_value": "1500000"})

    actions = _audit_actions(db_session, case["id"])
    assert actions.count("RENOVA_CASE_STATUS_CHANGED") == 1
    assert actions.count("RENOVA_CASE_ASSIGNEE_CHANGED") == 1
    assert actions.count("RENOVA_CASE_FINANCIALS_UPDATED") == 1
    assert actions.count("RENOVA_CASE_UPDATED") == 3


def test_a_patch_that_changes_nothing_writes_no_audit_row(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    case = _create(client, current_user, notes="igual", market_value="1000000")

    client.patch(f"{URL}/{case['id']}", json={"notes": "igual", "market_value": "1000000.00"})

    assert _audit_actions(db_session, case["id"]) == ["RENOVA_CASE_CREATED"]


# --- list, filters, search -----------------------------------------------------


def test_list_returns_lean_rows_newest_entry_first(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Antigua", entry_date="2026-08-01")
    _create(client, current_user, owner_name="Reciente", entry_date="2026-09-15")
    _create(client, current_user, owner_name="Intermedia", entry_date="2026-09-01")

    rows = client.get(URL).json()

    assert [r["owner_name"] for r in rows] == ["Reciente", "Intermedia", "Antigua"]
    assert "total_debt" in rows[0]
    # The listing never carries the long narrative / spouse / deeds fields.
    for hidden in ("notes", "spouse_name", "spouse_phone", "conditions", "has_deeds", "sale_reason", "marital_status"):
        assert hidden not in rows[0]


def test_list_search_by_owner_name_or_phone(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Ana Torres", owner_phone="+52 81 1111 2222")
    _create(client, current_user, owner_name="Luis Ramos", owner_phone="+52 55 9999 8888")

    assert [r["owner_name"] for r in client.get(URL, params={"q": "torres"}).json()] == ["Ana Torres"]
    assert [r["owner_name"] for r in client.get(URL, params={"q": "9999"}).json()] == ["Luis Ramos"]
    assert client.get(URL, params={"q": "nadie"}).json() == []


def test_search_treats_percent_and_underscore_literally(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Ana Torres")

    assert client.get(URL, params={"q": "%"}).json() == []
    assert client.get(URL, params={"q": "_"}).json() == []


def test_list_filter_by_status(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Nuevo")
    _create(client, current_user, owner_name="En revisión", status="reviewing")

    rows = client.get(URL, params={"status": "reviewing"}).json()

    assert [r["owner_name"] for r in rows] == ["En revisión"]
    assert client.get(URL, params={"status": "bogus"}).status_code == 422


def test_list_filter_by_advisor(client: TestClient, current_user: CurrentUser, db_session: Session):
    colleague = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(colleague)
    db_session.commit()
    _create(client, current_user, owner_name="Mío")
    client.post(URL, json=payload(colleague.id, owner_name="De la colega"))

    mine = client.get(URL, params={"assigned_user_id": str(current_user.id)}).json()
    theirs = client.get(URL, params={"assigned_user_id": str(colleague.id)}).json()

    assert [r["owner_name"] for r in mine] == ["Mío"]
    assert [r["owner_name"] for r in theirs] == ["De la colega"]


def test_list_pagination(client: TestClient, current_user: CurrentUser):
    for i in range(5):
        _create(client, current_user, owner_name=f"Caso {i}", entry_date=f"2026-09-{10 + i}")

    page = client.get(URL, params={"limit": 2, "offset": 2}).json()

    assert len(page) == 2
    assert client.get(URL, params={"limit": 0}).status_code == 422
    assert client.get(URL, params={"limit": 201}).status_code == 422


# --- organization isolation ------------------------------------------------------


def test_organizations_never_see_each_others_cases(db_session: Session):
    org_a, org_b = Organization(name="Org A"), Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()
    user_a = User(id=uuid.uuid4(), organization_id=org_a.id, role="owner")
    user_b = User(id=uuid.uuid4(), organization_id=org_b.id, role="owner")
    db_session.add_all([user_a, user_b])
    db_session.commit()
    cu_a = CurrentUser(id=user_a.id, email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    cu_b = CurrentUser(id=user_b.id, email="b@example.com", organization_id=org_b.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    try:
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_org_user] = lambda: cu_b
        case_b = TestClient(app).post(URL, json=payload(user_b.id, owner_name="Solo de B")).json()

        app.dependency_overrides[get_current_org_user] = lambda: cu_a
        client_a = TestClient(app)
        assert client_a.get(URL).json() == []
        assert client_a.get(URL, params={"q": "Solo"}).json() == []
        assert client_a.get(f"{URL}/{case_b['id']}").status_code == 404
        assert client_a.patch(f"{URL}/{case_b['id']}", json={"notes": "intruso"}).status_code == 404

        app.dependency_overrides[get_current_org_user] = lambda: cu_b
        assert TestClient(app).get(f"{URL}/{case_b['id']}").json()["notes"] is None
    finally:
        app.dependency_overrides.clear()


def test_requires_authentication():
    from fastapi.testclient import TestClient as TC

    assert TC(app).get(URL).status_code in (401, 403)
    assert TC(app).post(URL, json={}).status_code in (401, 403)


# --- address, occupancy and draft status ---------------------------------------


def test_address_and_occupancy_round_trip_and_update(client: TestClient, current_user: CurrentUser):
    case = _create(
        client,
        current_user,
        street_address="  Av. Constitución 123  ",
        neighborhood="Centro",
        municipality="Monterrey",
        postal_code="64000",
        occupancy_status="rented",
    )
    assert case["street_address"] == "Av. Constitución 123"
    assert (case["neighborhood"], case["municipality"], case["postal_code"]) == ("Centro", "Monterrey", "64000")
    assert case["occupancy_status"] == "rented"

    fetched = client.get(f"{URL}/{case['id']}").json()
    assert fetched["postal_code"] == "64000" and fetched["occupancy_status"] == "rented"

    updated = client.patch(f"{URL}/{case['id']}", json={"municipality": "San Nicolás", "occupancy_status": "vacant"}).json()
    assert updated["municipality"] == "San Nicolás" and updated["occupancy_status"] == "vacant"
    assert updated["street_address"] == "Av. Constitución 123"


def test_address_and_occupancy_are_optional_and_blank_becomes_null(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, street_address="   ", postal_code="")
    assert case["street_address"] is None and case["postal_code"] is None
    assert case["occupancy_status"] is None


@pytest.mark.parametrize("value", ["6400", "640001", "6400A", "64 00"])
def test_postal_code_must_be_exactly_five_digits(client: TestClient, current_user: CurrentUser, value: str):
    assert client.post(URL, json=payload(current_user.id, postal_code=value)).status_code == 422


def test_invalid_occupancy_status_is_rejected(client: TestClient, current_user: CurrentUser):
    assert client.post(URL, json=payload(current_user.id, occupancy_status="squatters")).status_code == 422


def test_list_items_do_not_carry_the_address(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, street_address="Calle Secreta 9")
    row = client.get(URL).json()[0]
    assert "street_address" not in row


def test_draft_status_can_be_created_and_promoted_with_an_audited_status_change(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    case = _create(client, current_user, status="draft")
    assert case["status"] == "draft"
    assert [c["status"] for c in client.get(URL, params={"status": "draft"}).json()] == ["draft"]

    promoted = client.patch(f"{URL}/{case['id']}", json={"status": "new"}).json()
    assert promoted["status"] == "new"
    assert "RENOVA_CASE_STATUS_CHANGED" in _audit_actions(db_session, case["id"])
