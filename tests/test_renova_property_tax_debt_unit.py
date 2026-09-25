"""
Renova's "Deuda predial" unit (app/models/renova_case.py, migration
c9e5f1a72b84): a WhatsApp conversation sometimes only reveals how many YEARS
of property tax are owed, never the peso amount. property_tax_debt_unit
("mxn"/"years") records which one was captured, and total_debt only sums it
when it's a real peso figure.
"""

import importlib.util
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
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


def test_defaults_to_mxn_when_not_specified(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)
    assert case["property_tax_debt_unit"] == "mxn"


def test_a_peso_amount_is_included_in_total_debt(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, property_tax_debt="12000", water_debt="800")
    assert case["property_tax_debt_unit"] == "mxn"
    assert case["total_debt"] == "12800.00"


def test_years_owed_is_stored_but_excluded_from_total_debt(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, property_tax_debt="3", property_tax_debt_unit="years", water_debt="800")
    assert case["property_tax_debt"] == "3.00"
    assert case["property_tax_debt_unit"] == "years"
    # Only the water debt counts — 3 YEARS can't be added to $800 MXN.
    assert case["total_debt"] == "800.00"


def test_years_owed_with_no_other_debt_leaves_total_debt_null(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, property_tax_debt="5", property_tax_debt_unit="years")
    assert case["total_debt"] is None


def test_years_must_be_a_whole_number(client: TestClient, current_user: CurrentUser):
    response = client.post(URL, json=payload(current_user.id, property_tax_debt="3.5", property_tax_debt_unit="years"))
    assert response.status_code == 422


def test_years_has_a_sane_upper_bound(client: TestClient, current_user: CurrentUser):
    too_many = client.post(URL, json=payload(current_user.id, property_tax_debt="61", property_tax_debt_unit="years"))
    assert too_many.status_code == 422

    at_the_limit = client.post(URL, json=payload(current_user.id, property_tax_debt="60", property_tax_debt_unit="years"))
    assert at_the_limit.status_code == 201


def test_an_invalid_unit_value_is_rejected(client: TestClient, current_user: CurrentUser):
    response = client.post(URL, json=payload(current_user.id, property_tax_debt_unit="anios"))
    assert response.status_code == 422


def test_editing_switches_the_unit_and_the_new_total_reflects_it(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, property_tax_debt="12000", water_debt="800")
    assert case["total_debt"] == "12800.00"

    updated = client.patch(f"{URL}/{case['id']}", json={"property_tax_debt": "4", "property_tax_debt_unit": "years"}).json()
    assert updated["property_tax_debt_unit"] == "years"
    assert updated["total_debt"] == "800.00"

    back = client.patch(f"{URL}/{case['id']}", json={"property_tax_debt": "9000", "property_tax_debt_unit": "mxn"}).json()
    assert back["total_debt"] == "9800.00"


def test_a_patch_with_both_fields_together_still_validates_the_combination(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    response = client.patch(f"{URL}/{case['id']}", json={"property_tax_debt": "3.5", "property_tax_debt_unit": "years"})

    assert response.status_code == 422


def test_a_patch_changing_only_the_unit_does_not_re_validate_the_already_stored_amount(
    client: TestClient, current_user: CurrentUser
):
    # Documents the tradeoff: partial updates only cross-validate fields sent
    # TOGETHER in the same request, same as every other field in this schema.
    case = _create(client, current_user, property_tax_debt="12000.50")

    response = client.patch(f"{URL}/{case['id']}", json={"property_tax_debt_unit": "years"})

    assert response.status_code == 200
    assert response.json()["property_tax_debt_unit"] == "years"


def test_property_tax_debt_unit_cannot_be_explicitly_nulled(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    response = client.patch(f"{URL}/{case['id']}", json={"property_tax_debt_unit": None})

    assert response.status_code == 422


def test_listing_includes_the_unit(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, property_tax_debt="5", property_tax_debt_unit="years")

    row = client.get(URL).json()[0]

    assert row["property_tax_debt_unit"] == "years"


def test_changing_the_unit_is_audited_as_a_financial_update(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create(client, current_user, property_tax_debt="12000")

    client.patch(f"{URL}/{case['id']}", json={"property_tax_debt_unit": "years"})

    actions = [
        r.action for r in db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(case["id"])).all()
    ]
    assert "RENOVA_CASE_FINANCIALS_UPDATED" in actions


def _load_migration(filename: str):
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chain():
    module = _load_migration("c9e5f1a72b84_add_renova_property_tax_debt_unit.py")
    assert module.revision == "c9e5f1a72b84"
    assert module.down_revision == "b2f7a4c9d310"
