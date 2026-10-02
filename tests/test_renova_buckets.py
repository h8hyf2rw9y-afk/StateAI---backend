"""
The Leads -> Renova table's three views (GET /renova/cases?bucket=active|
closed|archived) and their counters (GET /renova/cases/counts).

`bucket` is additive and server-side: it groups the SAME `status`/`archived`
columns tests/test_renova_archiving.py already covers, no new table, no case
copies. "active" = not archived and not rejected/cancelled. "closed" = not
archived and rejected/cancelled ("purchased" stays active -- it's a closed,
successful deal, not an exit). "archived" = archived=true, regardless of
status. Omitting `bucket` entirely must keep behaving exactly as before
(see test_renova_archiving.py's own listing tests, still passing unchanged).
"""

import uuid

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
        "street_address": "Calle Secreta 9",
        "market_value": "1500000",
    }
    body.update(overrides)
    return body


def _create(client: TestClient, user: CurrentUser, **overrides) -> dict:
    response = client.post(URL, json=payload(user.id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _bucket(client: TestClient, bucket: str) -> list[dict]:
    return client.get(URL, params={"bucket": bucket}).json()


def _audit_actions(db_session: Session, case_id: str) -> list[str]:
    rows = db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(case_id)).all()
    return sorted(r.action for r in rows)


# --- 1-3: active <-> closed transition ----------------------------------------


def test_an_active_case_appears_in_active_bucket(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Activo")

    assert [c["owner_name"] for c in _bucket(client, "active")] == ["Activo"]
    assert [c["owner_name"] for c in _bucket(client, "closed")] == []


def test_changing_to_cancelled_removes_it_from_active_bucket(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Se cancela")

    client.patch(f"{URL}/{case['id']}", json={"status": "cancelled"})

    assert [c["owner_name"] for c in _bucket(client, "active")] == []


def test_the_same_case_appears_in_closed_bucket_after_cancelling(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Se cancela")
    client.patch(f"{URL}/{case['id']}", json={"status": "cancelled"})

    closed = _bucket(client, "closed")

    assert [c["id"] for c in closed] == [case["id"]]


# --- 4: no data loss on a status change ---------------------------------------


def test_original_data_stays_intact_after_a_status_change(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Datos Intactos", street_address="Av. Siempre Viva 742")

    client.patch(f"{URL}/{case['id']}", json={"status": "rejected"})

    detail = client.get(f"{URL}/{case['id']}").json()
    assert detail["owner_name"] == "Datos Intactos"
    assert detail["street_address"] == "Av. Siempre Viva 742"
    assert detail["market_value"] == "1500000.00"


# --- 5-6: rejected vs cancelled are visually distinguishable -------------------


def test_a_rejected_case_shows_status_rejected_in_closed_bucket(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Rechazado", status="rejected")

    closed = _bucket(client, "closed")

    assert [c["status"] for c in closed if c["id"] == case["id"]] == ["rejected"]


def test_a_cancelled_case_shows_status_cancelled_in_closed_bucket(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Cancelado")
    client.patch(f"{URL}/{case['id']}", json={"status": "cancelled"})

    closed = _bucket(client, "closed")

    assert [c["status"] for c in closed if c["id"] == case["id"]] == ["cancelled"]


# --- 7-9: archive / restore / reactivate ---------------------------------------


def test_archiving_a_closed_case_moves_it_to_archived_bucket(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Se archiva", status="rejected")

    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    assert [c["id"] for c in _bucket(client, "closed")] == []
    assert [c["id"] for c in _bucket(client, "archived")] == [case["id"]]


def test_restoring_preserves_its_previous_status(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Se restaura", status="rejected")
    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    response = client.patch(f"{URL}/{case['id']}", json={"archived": False})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"  # not auto-reactivated
    assert [c["id"] for c in _bucket(client, "closed")] == [case["id"]]
    assert [c["id"] for c in _bucket(client, "archived")] == []


def test_reactivating_returns_it_to_active_bucket(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Se reactiva", status="cancelled")

    response = client.patch(f"{URL}/{case['id']}", json={"status": "new"})

    assert response.status_code == 200
    assert [c["id"] for c in _bucket(client, "active")] == [case["id"]]
    assert [c["id"] for c in _bucket(client, "closed")] == []


def test_archiving_then_reactivating_audits_both_steps(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create(client, current_user, status="rejected")
    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    client.patch(f"{URL}/{case['id']}", json={"archived": False})
    client.patch(f"{URL}/{case['id']}", json={"status": "new"})

    actions = _audit_actions(db_session, case["id"])
    assert "RENOVA_CASE_ARCHIVED" in actions
    assert "RENOVA_CASE_UNARCHIVED" in actions
    assert "RENOVA_CASE_STATUS_CHANGED" in actions


# --- 10: the popup always opens the correct case -------------------------------


def test_each_bucket_opens_the_correct_case_by_id(client: TestClient, current_user: CurrentUser):
    active = _create(client, current_user, owner_name="A")
    closed = _create(client, current_user, owner_name="B", status="rejected")
    archived = _create(client, current_user, owner_name="C", status="cancelled")
    client.patch(f"{URL}/{archived['id']}", json={"archived": True})

    for case in (active, closed, archived):
        detail = client.get(f"{URL}/{case['id']}").json()
        assert detail["id"] == case["id"]
        assert detail["owner_name"] == case["owner_name"]


# --- 12: table rows never carry sensitive data, in any bucket ------------------


def test_bucket_listings_never_expose_sensitive_fields(client: TestClient, current_user: CurrentUser):
    active = _create(client, current_user, nss="12345678901", credit_number="4111111111111111")
    closed = _create(client, current_user, status="rejected", nss="12345678901")
    archived = _create(client, current_user, status="cancelled")
    client.patch(f"{URL}/{archived['id']}", json={"archived": True})

    for bucket in ("active", "closed", "archived"):
        for row in _bucket(client, bucket):
            for field in ("nss", "nss_encrypted", "nss_masked", "credit_number", "credit_number_encrypted",
                          "credit_number_masked", "ine_front_encrypted", "ine_back_encrypted"):
                assert field not in row


# --- 13: organization isolation across every bucket ----------------------------


def test_an_organization_cannot_see_another_organizations_cases_in_any_bucket(db_session: Session):
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
        TestClient(app).post(URL, json=payload(user_b.id, status="rejected"))

        app.dependency_overrides[get_current_org_user] = lambda: cu_a
        client_a = TestClient(app)
        for bucket in ("active", "closed", "archived"):
            assert client_a.get(URL, params={"bucket": bucket}).json() == []
        assert client_a.get(f"{URL}/counts").json() == {
            "active": 0, "closed": 0, "rejected": 0, "cancelled": 0, "archived": 0,
        }
    finally:
        app.dependency_overrides.clear()


# --- 14: search, filters and counters compose with bucket ----------------------


def test_search_composes_with_bucket(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Ana Torres", status="rejected")
    _create(client, current_user, owner_name="Luis Ramos", status="rejected")

    result = client.get(URL, params={"bucket": "closed", "q": "torres"}).json()

    assert [c["owner_name"] for c in result] == ["Ana Torres"]


def test_status_filter_composes_with_bucket(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Rechazado", status="rejected")
    _create(client, current_user, owner_name="Cancelado", status="cancelled")

    result = client.get(URL, params={"bucket": "closed", "status": "rejected"}).json()

    assert [c["owner_name"] for c in result] == ["Rechazado"]


def test_omitting_bucket_keeps_the_original_behavior(client: TestClient, current_user: CurrentUser):
    visible = _create(client, current_user, owner_name="Visible")
    closed = _create(client, current_user, owner_name="Cerrado", status="rejected")
    archived = _create(client, current_user, owner_name="Archivado", status="cancelled")
    client.patch(f"{URL}/{archived['id']}", json={"archived": True})

    default_list = client.get(URL).json()

    # Unchanged from before `bucket` existed: only archived=false is applied,
    # so a closed-but-not-archived case still shows up here.
    assert {c["owner_name"] for c in default_list} == {"Visible", "Cerrado"}


def test_counts_endpoint_matches_the_bucket_listings(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="A1")
    _create(client, current_user, owner_name="A2")
    _create(client, current_user, owner_name="R1", status="rejected")
    cancelled = _create(client, current_user, owner_name="C1", status="cancelled")
    archived = _create(client, current_user, owner_name="Arch1", status="rejected")
    client.patch(f"{URL}/{archived['id']}", json={"archived": True})

    counts = client.get(f"{URL}/counts").json()

    assert counts == {"active": 2, "closed": 2, "rejected": 1, "cancelled": 1, "archived": 1}
    assert len(_bucket(client, "active")) == counts["active"]
    assert len(_bucket(client, "closed")) == counts["closed"]
    assert len(_bucket(client, "archived")) == counts["archived"]


# --- 15: no regressions in pipeline or archiving --------------------------------


def test_pipeline_board_is_unaffected_by_the_new_bucket_filter(client: TestClient, current_user: CurrentUser):
    active = _create(client, current_user, owner_name="En pipeline", status="negotiating")
    closed = _create(client, current_user, owner_name="Fuera del pipeline", status="rejected")

    pipeline = client.get("/api/v1/renova/pipeline").json()
    all_ids = [c["id"] for stage in pipeline["stages"] for c in stage["cases"]]

    assert active["id"] in all_ids
    assert closed["id"] not in all_ids
    # And it's still reachable through the closed bucket, same data.
    assert [c["id"] for c in _bucket(client, "closed")] == [closed["id"]]


def test_archiving_flow_from_test_renova_archiving_still_works_with_bucket_present(
    client: TestClient, current_user: CurrentUser
):
    case = _create(client, current_user, status="cancelled")

    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    assert client.get(URL).json() == []  # default listing still hides it
    assert [c["id"] for c in _bucket(client, "archived")] == [case["id"]]
