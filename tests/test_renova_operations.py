"""Post-acceptance Renova operations stay separate from lead buckets/status history."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.schemas.enums import RENOVA_OPERATION_STAGES
from app.schemas.user import CurrentUser

CASES_URL = "/api/v1/renova/cases"
OPERATIONS_URL = "/api/v1/renova/operations"


def payload(user_id: uuid.UUID, **overrides) -> dict:
    body = {
        "assigned_user_id": str(user_id),
        "entry_date": "2026-10-06",
        "owner_name": "María López",
        "owner_phone": "+52 81 5555 0101",
    }
    body.update(overrides)
    return body


def create_case(client: TestClient, user: CurrentUser, **overrides) -> dict:
    response = client.post(CASES_URL, json=payload(user.id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def all_cards(response: dict) -> list[dict]:
    return [card for group in response["stages"] for card in group["cases"]]


def test_operations_returns_every_stage_in_business_order(client: TestClient):
    response = client.get(OPERATIONS_URL)

    assert response.status_code == 200
    assert [group["stage"] for group in response.json()["stages"]] == list(RENOVA_OPERATION_STAGES)


def test_accepting_a_proposal_starts_the_operation_without_changing_bucket_logic(
    client: TestClient, current_user: CurrentUser
):
    case = create_case(client, current_user)

    accepted = client.patch(f"{CASES_URL}/{case['id']}", json={"status": "accepted"})
    operations = client.get(OPERATIONS_URL).json()
    active = client.get(CASES_URL, params={"bucket": "active"}).json()

    assert accepted.status_code == 200
    card = next(card for card in all_cards(operations) if card["id"] == case["id"])
    assert card["operation_stage"] == "proposal_accepted"
    assert any(item["id"] == case["id"] for item in active)


def test_legacy_purchased_case_starts_at_renovation(client: TestClient, current_user: CurrentUser):
    case = create_case(client, current_user, status="purchased")

    card = next(card for card in all_cards(client.get(OPERATIONS_URL).json()) if card["id"] == case["id"])

    assert card["operation_stage"] == "renovation"
    assert card["status"] == "purchased"


def test_operation_stage_and_next_action_are_editable(client: TestClient, current_user: CurrentUser):
    case = create_case(client, current_user, status="accepted")

    response = client.patch(
        f"{CASES_URL}/{case['id']}/operation",
        json={
            "operation_stage": "notary_contract",
            "operation_next_action": "Firmar carta poder",
            "operation_due_at": "2026-10-09T16:00:00-06:00",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["operation_stage"] == "notary_contract"
    assert body["operation_next_action"] == "Firmar carta poder"
    assert body["operation_due_at"].startswith("2026-10-09T")
    assert body["operation_stage_updated_at"] is not None


def test_reaching_renovation_syncs_the_coarse_status_to_purchased(
    client: TestClient, current_user: CurrentUser
):
    case = create_case(client, current_user, status="accepted")

    moved = client.patch(
        f"{CASES_URL}/{case['id']}/operation", json={"operation_stage": "renovation"}
    )

    assert moved.status_code == 200
    assert moved.json()["status"] == "purchased"
    assert client.get(f"{CASES_URL}/{case['id']}").json()["status"] == "purchased"


def test_moving_back_before_purchase_syncs_status_to_accepted(client: TestClient, current_user: CurrentUser):
    case = create_case(client, current_user, status="purchased")

    moved = client.patch(
        f"{CASES_URL}/{case['id']}/operation", json={"operation_stage": "site_survey"}
    )

    assert moved.status_code == 200
    assert moved.json()["status"] == "accepted"


def test_unaccepted_case_cannot_enter_operations(client: TestClient, current_user: CurrentUser):
    case = create_case(client, current_user)

    response = client.patch(
        f"{CASES_URL}/{case['id']}/operation", json={"operation_stage": "site_survey"}
    )

    assert response.status_code == 422
    assert all(card["id"] != case["id"] for card in all_cards(client.get(OPERATIONS_URL).json()))


def test_rejected_cancelled_and_archived_views_remain_separate(
    client: TestClient, current_user: CurrentUser
):
    rejected = create_case(client, current_user, status="accepted", owner_name="Rechazado")
    client.patch(f"{CASES_URL}/{rejected['id']}", json={"status": "rejected"})
    cancelled = create_case(client, current_user, status="accepted", owner_name="Cancelado")
    client.patch(f"{CASES_URL}/{cancelled['id']}", json={"status": "cancelled"})
    client.patch(f"{CASES_URL}/{cancelled['id']}", json={"archived": True})

    operation_ids = {card["id"] for card in all_cards(client.get(OPERATIONS_URL).json())}
    closed_ids = {item["id"] for item in client.get(CASES_URL, params={"bucket": "closed"}).json()}
    archived_ids = {item["id"] for item in client.get(CASES_URL, params={"bucket": "archived"}).json()}

    assert rejected["id"] not in operation_ids and cancelled["id"] not in operation_ids
    assert rejected["id"] in closed_ids and cancelled["id"] not in closed_ids
    assert cancelled["id"] in archived_ids


def test_operation_card_never_exposes_protected_data(client: TestClient, current_user: CurrentUser):
    case = create_case(
        client,
        current_user,
        status="accepted",
        nss="12345678901",
        credit_number="9876543210",
    )

    raw = client.get(OPERATIONS_URL).text
    card = next(card for card in all_cards(client.get(OPERATIONS_URL).json()) if card["id"] == case["id"])

    assert "12345678901" not in raw and "9876543210" not in raw
    assert not any("nss" in key or "credit_number" in key or "ine" in key or "encrypted" in key for key in card)


def test_operation_changes_are_audited(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    case = create_case(client, current_user, status="accepted")

    client.patch(
        f"{CASES_URL}/{case['id']}/operation",
        json={"operation_stage": "site_survey", "operation_next_action": "Medir propiedad"},
    )

    row = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity_id == uuid.UUID(case["id"]),
            AuditLog.action == "RENOVA_OPERATION_STAGE_CHANGED",
        )
        .one()
    )
    assert row.actor_user_id == current_user.id
    assert row.before_data["operation_stage"] == "proposal_accepted"
    assert row.after_data["operation_stage"] == "site_survey"
    assert row.after_data["operation_next_action"] == "Medir propiedad"


def test_operation_update_can_clear_optional_schedule(client: TestClient, current_user: CurrentUser):
    case = create_case(client, current_user, status="accepted")
    client.patch(
        f"{CASES_URL}/{case['id']}/operation",
        json={"operation_next_action": "Llamar", "operation_due_at": "2026-10-09T16:00:00Z"},
    )

    cleared = client.patch(
        f"{CASES_URL}/{case['id']}/operation",
        json={"operation_next_action": None, "operation_due_at": None},
    )

    assert cleared.status_code == 200
    assert cleared.json()["operation_next_action"] is None
    assert cleared.json()["operation_due_at"] is None
