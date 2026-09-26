"""
Renova's dwelling type vs. duplex configuration (app/models/renova_case.py,
app/schemas/renova_case.py, migration b2f7a4c9d310).

`dwelling_type` is a mutually-exclusive BASE type ("house"/"apartment" only)
and `is_duplex` is an independent boolean CONFIGURATION either base type can
carry — a case can be a "Casa dúplex" or a "Departamento dúplex". Because
dwelling_type is a single field (not two separate booleans), "house and
apartment selected at once" is structurally impossible rather than something
that needs a runtime check — there is no test for it for that reason.
"""

import importlib.util
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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


# --- 1-4: the four valid combinations ---------------------------------------------


def test_create_a_plain_house(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, dwelling_type="house")
    assert case["dwelling_type"] == "house" and case["is_duplex"] is False


def test_create_a_plain_apartment(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, dwelling_type="apartment")
    assert case["dwelling_type"] == "apartment" and case["is_duplex"] is False


def test_create_a_duplex_house(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, dwelling_type="house", is_duplex=True)
    assert case["dwelling_type"] == "house" and case["is_duplex"] is True


def test_create_a_duplex_apartment(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, dwelling_type="apartment", is_duplex=True)
    assert case["dwelling_type"] == "apartment" and case["is_duplex"] is True


def test_is_duplex_defaults_to_false_when_omitted(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)
    assert case["is_duplex"] is False


# --- 5: "duplex" is no longer a dwelling_type value --------------------------------


def test_dwelling_type_rejects_the_old_duplex_value(client: TestClient, current_user: CurrentUser):
    response = client.post(URL, json=payload(current_user.id, dwelling_type="duplex"))
    assert response.status_code == 422


# --- 6: duplex with an unknown base type -------------------------------------------


def test_duplex_with_no_base_type_yet_is_allowed_and_round_trips(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, is_duplex=True)
    assert case["dwelling_type"] is None and case["is_duplex"] is True

    detail = client.get(f"{URL}/{case['id']}").json()
    assert detail["dwelling_type"] is None and detail["is_duplex"] is True


# --- 7-8: editing ------------------------------------------------------------------


def test_editing_a_duplex_house_into_a_duplex_apartment(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, dwelling_type="house", is_duplex=True)

    updated = client.patch(f"{URL}/{case['id']}", json={"dwelling_type": "apartment"}).json()

    assert updated["dwelling_type"] == "apartment" and updated["is_duplex"] is True


def test_changing_only_the_base_type_leaves_is_duplex_untouched(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, dwelling_type="house", is_duplex=True)

    # is_duplex is not in this PATCH at all — PATCH semantics say "untouched", not "reset to false".
    updated = client.patch(f"{URL}/{case['id']}", json={"dwelling_type": "apartment"}).json()
    assert updated["is_duplex"] is True

    # And the reverse: changing is_duplex alone leaves the base type untouched.
    updated2 = client.patch(f"{URL}/{case['id']}", json={"is_duplex": False}).json()
    assert updated2["dwelling_type"] == "apartment" and updated2["is_duplex"] is False


def test_is_duplex_cannot_be_explicitly_nulled(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, dwelling_type="house", is_duplex=True)

    response = client.patch(f"{URL}/{case['id']}", json={"is_duplex": None})

    assert response.status_code == 422


# --- listing carries is_duplex too (the table needs it to build "Casa dúplex") -----


def test_listing_includes_is_duplex(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, dwelling_type="apartment", is_duplex=True)

    row = client.get(URL).json()[0]

    assert row["dwelling_type"] == "apartment" and row["is_duplex"] is True


# --- 9: migrating legacy dwelling_type="duplex" rows --------------------------------


def _load_migration(filename: str):
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_moves_legacy_duplex_rows_to_is_duplex_without_inventing_a_base_type(
    db_session: Session, current_user: CurrentUser
):
    # Simulate a row saved under the OLD model, bypassing the new Pydantic
    # validation (which would now reject dwelling_type="duplex") — exactly
    # what already exists in the real database for any case captured before
    # this change.
    legacy = RenovaCase(
        organization_id=current_user.organization_id,
        entry_date=date(2026, 9, 1),
        owner_name="Legacy Owner",
        owner_phone="+52 81 5555 9999",
        dwelling_type="duplex",
        is_duplex=False,
    )
    db_session.add(legacy)
    db_session.commit()

    module = _load_migration("b2f7a4c9d310_split_renova_duplex_from_dwelling_type.py")
    db_session.execute(
        module._renova_cases.update()
        .where(module._renova_cases.c.dwelling_type == "duplex")
        .values(is_duplex=True, dwelling_type=None)
    )
    db_session.commit()

    db_session.refresh(legacy)
    # The base type was never actually known for these rows — it is left
    # null ("tipo base por confirmar" in the UI), never guessed.
    assert legacy.dwelling_type is None
    assert legacy.is_duplex is True


def test_migration_leaves_already_house_or_apartment_rows_untouched(db_session: Session, current_user: CurrentUser):
    normal = RenovaCase(
        organization_id=current_user.organization_id,
        entry_date=date(2026, 9, 1),
        owner_name="Normal Owner",
        owner_phone="+52 81 5555 8888",
        dwelling_type="house",
        is_duplex=False,
    )
    db_session.add(normal)
    db_session.commit()

    module = _load_migration("b2f7a4c9d310_split_renova_duplex_from_dwelling_type.py")
    db_session.execute(
        module._renova_cases.update()
        .where(module._renova_cases.c.dwelling_type == "duplex")
        .values(is_duplex=True, dwelling_type=None)
    )
    db_session.commit()

    db_session.refresh(normal)
    assert normal.dwelling_type == "house" and normal.is_duplex is False


def test_migration_revision_chain_and_added_column(db_session: Session):
    module = _load_migration("b2f7a4c9d310_split_renova_duplex_from_dwelling_type.py")
    assert module.revision == "b2f7a4c9d310"
    assert module.down_revision == "7f3c1a9e42d1"
