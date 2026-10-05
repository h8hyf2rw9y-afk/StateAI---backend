"""
Renova's structured proposal model (app/models/renova_case.py's
proposal_type/debt_coverage_amount/owner_cash_offer, migration
dbec420e1b00). Covers validation per modality, the single
total_proposal_value computation, the legacy `final_offer` sync, and that
no existing ambiguous record is ever silently reclassified.
"""

import importlib.util
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User
from app.models.renova_case import RenovaCase
from app.schemas.user import CurrentUser

URL = "/api/v1/renova/cases"
BACKEND_ROOT = Path(__file__).resolve().parent.parent


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


# --- valid proposals, per modality --------------------------------------------


def test_debt_only_is_a_complete_valid_proposal(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, proposal_type="debt_only", debt_coverage_amount="320000")

    assert case["proposal_type"] == "debt_only"
    assert case["debt_coverage_amount"] == "320000.00"
    assert case["owner_cash_offer"] is None
    assert case["total_proposal_value"] == "320000.00"
    # The legacy column stays in sync for anything still reading it directly.
    assert case["final_offer"] == "320000.00"


def test_debt_plus_cash_sums_both_amounts(client: TestClient, current_user: CurrentUser):
    case = _create(
        client, current_user, proposal_type="debt_plus_cash", debt_coverage_amount="320000", owner_cash_offer="140000"
    )

    assert case["total_proposal_value"] == "460000.00"
    assert case["final_offer"] == "460000.00"


def test_cash_only_proposal(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, proposal_type="cash_only", owner_cash_offer="150000")

    assert case["debt_coverage_amount"] is None
    assert case["total_proposal_value"] == "150000.00"


def test_debt_only_with_explicit_zero_cash_is_still_valid_and_not_dropped(client: TestClient, current_user: CurrentUser):
    """A debt_only proposal may explicitly carry owner_cash_offer=0 (not null) -- that must not change the total or be rejected."""
    case = _create(
        client, current_user, proposal_type="debt_only", debt_coverage_amount="320000", owner_cash_offer="0"
    )

    assert case["owner_cash_offer"] == "0.00"
    assert case["total_proposal_value"] == "320000.00"


def test_zero_cash_is_never_shown_as_no_proposal(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, proposal_type="debt_only", debt_coverage_amount="320000")

    assert case["total_proposal_value"] is not None
    assert Decimal(case["total_proposal_value"]) > 0


# --- modality validation ------------------------------------------------------


def test_debt_only_requires_a_positive_debt_coverage_amount(client: TestClient, current_user: CurrentUser):
    response = client.post(URL, json=payload(current_user.id, proposal_type="debt_only"))
    assert response.status_code == 422


def test_debt_only_rejects_a_positive_owner_cash_offer(client: TestClient, current_user: CurrentUser):
    response = client.post(
        URL,
        json=payload(current_user.id, proposal_type="debt_only", debt_coverage_amount="320000", owner_cash_offer="1"),
    )
    assert response.status_code == 422


def test_debt_plus_cash_requires_both_amounts(client: TestClient, current_user: CurrentUser):
    missing_cash = client.post(
        URL, json=payload(current_user.id, proposal_type="debt_plus_cash", debt_coverage_amount="320000")
    )
    missing_coverage = client.post(
        URL, json=payload(current_user.id, proposal_type="debt_plus_cash", owner_cash_offer="140000")
    )
    assert missing_cash.status_code == 422
    assert missing_coverage.status_code == 422


def test_cash_only_requires_a_positive_cash_offer_and_rejects_coverage(client: TestClient, current_user: CurrentUser):
    zero_cash = client.post(URL, json=payload(current_user.id, proposal_type="cash_only", owner_cash_offer="0"))
    with_coverage = client.post(
        URL, json=payload(current_user.id, proposal_type="cash_only", owner_cash_offer="150000", debt_coverage_amount="1")
    )
    assert zero_cash.status_code == 422
    assert with_coverage.status_code == 422


def test_unclassified_proposal_needs_no_amounts_at_all(client: TestClient, current_user: CurrentUser):
    """proposal_type omitted entirely -- a case may simply have no proposal yet, and that is not an error."""
    case = _create(client, current_user)

    assert case["proposal_type"] is None
    assert case["total_proposal_value"] is None
    assert case["final_offer"] is None


# --- known debt vs. proposed coverage: a warning signal, never a hard block --


def test_debt_coverage_may_differ_from_known_debt_without_being_blocked(client: TestClient, current_user: CurrentUser):
    case = _create(
        client, current_user,
        proposal_type="debt_only", debt_coverage_amount="200000",
        property_tax_debt="12000", other_debt="320000",  # known debt totals 332000, far from the 200000 covered
    )

    assert case["debt_coverage_amount"] == "200000.00"
    assert Decimal(case["total_debt"]) != Decimal(case["debt_coverage_amount"])


# --- PATCH: classifying an existing case, and re-classifying it --------------


def test_patch_can_classify_a_previously_unclassified_case(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    response = client.patch(
        f"{URL}/{case['id']}",
        json={"proposal_type": "debt_plus_cash", "debt_coverage_amount": "320000", "owner_cash_offer": "140000"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_proposal_value"] == "460000.00"
    assert body["final_offer"] == "460000.00"


def test_patch_rejects_an_incomplete_modality_change(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    response = client.patch(f"{URL}/{case['id']}", json={"proposal_type": "debt_only"})

    assert response.status_code == 422


def test_patch_can_reclassify_from_one_modality_to_another(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, proposal_type="debt_only", debt_coverage_amount="320000")

    response = client.patch(
        f"{URL}/{case['id']}",
        json={"proposal_type": "cash_only", "debt_coverage_amount": None, "owner_cash_offer": "150000"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal_type"] == "cash_only"
    assert body["debt_coverage_amount"] is None
    assert body["total_proposal_value"] == "150000.00"


# --- legacy / ambiguous historical records ------------------------------------


def test_a_legacy_case_with_only_final_offer_is_never_auto_classified(client: TestClient, current_user: CurrentUser, db_session: Session):
    """Simulates a pre-existing row from before this model: final_offer set directly, proposal_type never touched."""
    legacy = RenovaCase(
        organization_id=current_user.organization_id,
        assigned_user_id=current_user.id,
        entry_date=date(2026, 8, 1),
        owner_name="Legado",
        owner_phone="+52 81 0000 0000",
        final_offer=Decimal("275000"),
    )
    db_session.add(legacy)
    db_session.commit()

    body = client.get(f"{URL}/{legacy.id}").json()

    assert body["proposal_type"] is None
    assert body["debt_coverage_amount"] is None
    assert body["owner_cash_offer"] is None
    assert body["total_proposal_value"] is None
    # The ambiguous historical value is preserved exactly, not discarded.
    assert body["final_offer"] == "275000.00"


def test_reading_a_legacy_case_does_not_change_it(client: TestClient, current_user: CurrentUser, db_session: Session):
    legacy = RenovaCase(
        organization_id=current_user.organization_id, assigned_user_id=current_user.id,
        entry_date=date(2026, 8, 1), owner_name="Legado", owner_phone="+52 81 0000 0000",
        final_offer=Decimal("275000"),
    )
    db_session.add(legacy)
    db_session.commit()

    client.get(f"{URL}/{legacy.id}")
    client.get(URL)

    db_session.refresh(legacy)
    assert legacy.final_offer == Decimal("275000.00")
    assert legacy.proposal_type is None


def test_an_unrelated_patch_does_not_touch_a_legacy_cases_final_offer(client: TestClient, current_user: CurrentUser, db_session: Session):
    legacy = RenovaCase(
        organization_id=current_user.organization_id, assigned_user_id=current_user.id,
        entry_date=date(2026, 8, 1), owner_name="Legado", owner_phone="+52 81 0000 0000",
        final_offer=Decimal("275000"),
    )
    db_session.add(legacy)
    db_session.commit()

    response = client.patch(f"{URL}/{legacy.id}", json={"notes": "Seguimiento telefónico"})

    assert response.status_code == 200
    assert response.json()["final_offer"] == "275000.00"
    assert response.json()["proposal_type"] is None


# --- audit --------------------------------------------------------------------


def test_classifying_a_proposal_is_audited_as_a_financial_update(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create(client, current_user)

    client.patch(f"{URL}/{case['id']}", json={"proposal_type": "debt_only", "debt_coverage_amount": "320000"})

    assert "RENOVA_CASE_FINANCIALS_UPDATED" in _audit_actions(db_session, case["id"])


def test_audit_never_exposes_more_than_the_normal_read_shape(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create(client, current_user, proposal_type="cash_only", owner_cash_offer="150000")

    row = db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(case["id"])).first()

    assert row.after_data["proposal_type"] == "cash_only"
    assert row.after_data["owner_cash_offer"] == "150000.00" or row.after_data["owner_cash_offer"] == 150000.0


# --- organization isolation ---------------------------------------------------


def test_an_organization_cannot_read_or_classify_another_organizations_case(db_session: Session):
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
        case_b = TestClient(app).post(URL, json=payload(user_b.id, proposal_type="debt_only", debt_coverage_amount="320000")).json()

        app.dependency_overrides[get_current_org_user] = lambda: cu_a
        client_a = TestClient(app)
        assert client_a.get(f"{URL}/{case_b['id']}").status_code == 404
        assert client_a.patch(f"{URL}/{case_b['id']}", json={"proposal_type": "cash_only", "owner_cash_offer": "1"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


# --- migration -----------------------------------------------------------------


def _load_migration(filename: str):
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chain():
    module = _load_migration("dbec420e1b00_add_renova_proposal_model.py")
    assert module.revision == "dbec420e1b00"
    assert module.down_revision == "afb09875036b"
