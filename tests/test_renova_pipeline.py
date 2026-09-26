"""
The Renova Kanban board (GET /renova/pipeline, app/schemas/enums.py's
RENOVA_PIPELINE_STAGES, RenovaCaseService.pipeline). Stage moves reuse the
existing PATCH /renova/cases/{id} — see app/services/renova_case_service.py's
`update`, which already validates organization ownership and already records
RENOVA_CASE_STATUS_CHANGED when `status` changes, so there is no separate
move endpoint or audit action here.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User
from app.schemas.enums import RENOVA_PIPELINE_STAGES
from app.schemas.user import CurrentUser

CASES_URL = "/api/v1/renova/cases"
PIPELINE_URL = "/api/v1/renova/pipeline"


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
    response = client.post(CASES_URL, json=payload(user.id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _set_status(client: TestClient, case_id: str, status: str) -> dict:
    response = client.patch(f"{CASES_URL}/{case_id}", json={"status": status})
    assert response.status_code == 200, response.text
    return response.json()


def _stage_names(pipeline: dict) -> list[str]:
    return [s["status"] for s in pipeline["stages"]]


def _cases_in(pipeline: dict, status: str) -> list[dict]:
    return next(s["cases"] for s in pipeline["stages"] if s["status"] == status)


def _owner_names_by_stage(pipeline: dict) -> dict[str, list[str]]:
    return {s["status"]: [c["owner_name"] for c in s["cases"]] for s in pipeline["stages"]}


# --- shape and stage order ---------------------------------------------------


def test_pipeline_returns_exactly_the_six_stages_in_order(client: TestClient, current_user: CurrentUser):
    pipeline = client.get(PIPELINE_URL).json()

    assert _stage_names(pipeline) == list(RENOVA_PIPELINE_STAGES)
    assert list(RENOVA_PIPELINE_STAGES) == [
        "new", "offer_preparation", "offer_sent", "negotiating", "accepted", "purchased",
    ]


def test_each_case_appears_in_its_own_stage_column(client: TestClient, current_user: CurrentUser):
    a = _create(client, current_user, owner_name="Cliente A")
    b = _create(client, current_user, owner_name="Cliente B")
    _set_status(client, b["id"], "offer_preparation")
    c = _create(client, current_user, owner_name="Cliente C")
    _set_status(client, c["id"], "negotiating")

    by_stage = _owner_names_by_stage(client.get(PIPELINE_URL).json())

    assert by_stage["new"] == ["Cliente A"]
    assert by_stage["offer_preparation"] == ["Cliente B"]
    assert by_stage["negotiating"] == ["Cliente C"]
    assert by_stage["offer_sent"] == by_stage["accepted"] == by_stage["purchased"] == []


@pytest.mark.parametrize("excluded_status", ["draft", "rejected", "cancelled", "reviewing"])
def test_cases_outside_the_purchase_flow_never_appear_on_the_board(
    client: TestClient, current_user: CurrentUser, excluded_status: str
):
    if excluded_status == "draft":
        case = _create(client, current_user, status="draft")
    else:
        case = _create(client, current_user)
        _set_status(client, case["id"], excluded_status)

    pipeline = client.get(PIPELINE_URL).json()

    all_ids = [c["id"] for stage in pipeline["stages"] for c in stage["cases"]]
    assert case["id"] not in all_ids
    # It's excluded from the board, never deleted.
    assert client.get(f"{CASES_URL}/{case['id']}").json()["status"] == excluded_status


def test_purchased_cases_do_appear_as_the_final_column(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Comprado Feliz")
    _set_status(client, case["id"], "purchased")

    pipeline = client.get(PIPELINE_URL).json()

    assert _stage_names(pipeline)[-1] == "purchased"
    assert [c["owner_name"] for c in _cases_in(pipeline, "purchased")] == ["Comprado Feliz"]


# --- moving a case between stages -------------------------------------------


def test_moving_one_case_does_not_touch_any_other_case(client: TestClient, current_user: CurrentUser):
    target = _create(client, current_user, owner_name="Se mueve", market_value="900000")
    other = _create(client, current_user, owner_name="No se toca", market_value="500000")

    _set_status(client, target["id"], "offer_preparation")

    by_stage = _owner_names_by_stage(client.get(PIPELINE_URL).json())
    assert by_stage["offer_preparation"] == ["Se mueve"]
    assert by_stage["new"] == ["No se toca"]
    untouched = client.get(f"{CASES_URL}/{other['id']}").json()
    assert untouched["status"] == "new" and untouched["market_value"] == "500000.00"


def test_moving_a_case_is_audited_with_the_previous_and_new_status(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    case = _create(client, current_user)

    _set_status(client, case["id"], "offer_preparation")

    rows = db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(case["id"])).all()
    status_rows = [r for r in rows if r.action == "RENOVA_CASE_STATUS_CHANGED"]
    assert len(status_rows) == 1
    row = status_rows[0]
    assert row.actor_user_id == current_user.id
    assert row.before_data["status"] == "new"
    assert row.after_data["status"] == "offer_preparation"
    assert row.created_at is not None


# --- lean card shape: no protected data --------------------------------------


def test_pipeline_card_never_exposes_nss_credit_number_ine_or_ciphertext(
    client: TestClient, current_user: CurrentUser
):
    case = client.post(
        CASES_URL,
        json=payload(current_user.id, nss="12345678901", credit_number="123456"),
    ).json()

    raw_body = client.get(PIPELINE_URL).text

    assert "12345678901" not in raw_body
    assert "123456" not in raw_body
    for forbidden_key in ["nss", "credit_number", "encrypted", "ine_front", "ine_back"]:
        assert forbidden_key not in raw_body

    card = next(c for stage in client.get(PIPELINE_URL).json()["stages"] for c in stage["cases"] if c["id"] == case["id"])
    assert set(card.keys()) == {
        "id", "owner_name", "owner_phone", "status", "assigned_user_id", "dwelling_type", "is_duplex",
        "final_offer", "market_value", "other_debt", "property_tax_debt", "property_tax_debt_unit",
        "owner_expected_amount", "updated_at",
    }


# --- organization isolation ---------------------------------------------------


def test_an_organization_cannot_see_or_move_another_organizations_cases(db_session: Session):
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
        case_b = TestClient(app).post(CASES_URL, json=payload(user_b.id, owner_name="Solo de B")).json()

        app.dependency_overrides[get_current_org_user] = lambda: cu_a
        client_a = TestClient(app)
        pipeline_a = client_a.get(PIPELINE_URL).json()
        assert all(c["id"] != case_b["id"] for stage in pipeline_a["stages"] for c in stage["cases"])
        assert client_a.patch(f"{CASES_URL}/{case_b['id']}", json={"status": "offer_preparation"}).status_code == 404

        app.dependency_overrides[get_current_org_user] = lambda: cu_b
        assert TestClient(app).get(f"{CASES_URL}/{case_b['id']}").json()["status"] == "new"
    finally:
        app.dependency_overrides.clear()


def test_requires_authentication():
    from fastapi.testclient import TestClient as TC

    assert TC(app).get(PIPELINE_URL).status_code in (401, 403)


# --- filters on the plain listing keep working alongside the new endpoint ----


def test_the_plain_listings_own_filters_are_unaffected_by_the_pipeline_endpoint(
    client: TestClient, current_user: CurrentUser
):
    _create(client, current_user, owner_name="Ana Buscada", owner_phone="+52 81 1111 1111")
    _create(client, current_user, owner_name="Beto Distinto", owner_phone="+52 81 2222 2222")

    by_name = client.get(CASES_URL, params={"q": "Buscada"}).json()
    by_status = client.get(CASES_URL, params={"status": "new"}).json()

    assert [c["owner_name"] for c in by_name] == ["Ana Buscada"]
    assert len(by_status) == 2


# --- no pagination gap --------------------------------------------------------


def test_the_pipeline_never_truncates_even_well_past_the_plain_listings_default_page_size(
    client: TestClient, current_user: CurrentUser
):
    for i in range(60):
        _create(client, current_user, owner_name=f"Caso {i}")

    pipeline = client.get(PIPELINE_URL).json()

    assert len(_cases_in(pipeline, "new")) == 60
