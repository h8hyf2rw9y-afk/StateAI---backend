"""
Renova's sensitive-data guarantees. NSS and credit number must:
  * be stored only as ciphertext,
  * never be returned in full by any endpoint (masked in detail, absent in lists),
  * never appear in AuditLog snapshots, logs, or error responses,
  * never be readable by an AI agent,
and Renova must remain structurally separate from the traditional CRM.

The values below are obviously fake test strings, not realistic identifiers.
"""

import importlib.util
import base64
import io
import json
import logging
import re
import uuid
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.renova_case import RenovaCase
from app.schemas.user import CurrentUser

URL = "/api/v1/renova/cases"
FAKE_NSS = "00445566789"
FAKE_CREDIT = "0908172630"
REPLACEMENT_NSS = "99887766554"
NSS_LAST4 = FAKE_NSS[-4:]


def mask(value: str) -> str:
    return "•" * (len(value) - 4) + value[-4:]

CREDIT_LAST4 = FAKE_CREDIT[-4:]

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _body(user: CurrentUser, **overrides) -> dict:
    body = {
        "assigned_user_id": str(user.id),
        "entry_date": "2026-09-20",
        "owner_name": "María López",
        "owner_phone": "+52 81 5555 0101",
    }
    body.update(overrides)
    return body


def _create_with_secrets(client: TestClient, user: CurrentUser, **overrides) -> dict:
    response = client.post(URL, json=_body(user, nss=FAKE_NSS, credit_number=FAKE_CREDIT, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


# --- storage -------------------------------------------------------------------


def test_sensitive_fields_are_stored_as_ciphertext_only(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    case = _create_with_secrets(client, current_user)

    row = db_session.get(RenovaCase, uuid.UUID(case["id"]))
    assert row.nss_encrypted and row.credit_number_encrypted
    assert FAKE_NSS not in row.nss_encrypted and FAKE_CREDIT not in row.credit_number_encrypted
    # ...and it round-trips through the real cipher.
    assert crypto.decrypt_secret(row.nss_encrypted) == FAKE_NSS
    assert crypto.decrypt_secret(row.credit_number_encrypted) == FAKE_CREDIT
    # The only NSS/credit columns on the table are the encrypted ones.
    assert {c for c in RenovaCase.__table__.columns.keys() if "nss" in c or "credit" in c} == {
        "nss_encrypted",
        "credit_number_encrypted",
    }


def test_ine_images_are_encrypted_and_only_revealed_via_protected_endpoint(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    case = _create_with_secrets(client, current_user)
    image = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"fake-image-content").decode()
    path = f"{URL}/{case['id']}/ine/front"
    assert client.put(path, json={"image": image}).status_code == 204
    row = db_session.get(RenovaCase, uuid.UUID(case["id"]))
    assert row.ine_front_encrypted and image not in row.ine_front_encrypted
    assert image not in client.get(f"{URL}/{case['id']}").text
    assert image not in client.get(URL).text
    revealed = client.get(path)
    assert revealed.status_code == 200
    assert revealed.json() == {"image": image}
    assert revealed.headers["Cache-Control"] == "no-store"
    assert client.put(path, json={"image": "data:image/png;base64,bogus"}).status_code == 422


def test_no_plaintext_anywhere_in_the_row(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create_with_secrets(client, current_user)

    row = db_session.get(RenovaCase, uuid.UUID(case["id"]))
    blob = json.dumps({c.name: str(getattr(row, c.name)) for c in RenovaCase.__table__.columns})
    assert FAKE_NSS not in blob and FAKE_CREDIT not in blob


# --- API responses ---------------------------------------------------------------


def test_create_and_detail_return_only_masked_values(client: TestClient, current_user: CurrentUser):
    created = _create_with_secrets(client, current_user)
    detail = client.get(f"{URL}/{created['id']}").json()

    for body in (created, detail):
        assert body["nss_masked"] == mask(FAKE_NSS)
        assert body["credit_number_masked"] == mask(FAKE_CREDIT)
        raw = json.dumps(body)
        assert FAKE_NSS not in raw and FAKE_CREDIT not in raw
        # No field named like the write-only input is echoed back.
        assert "nss" not in body and "credit_number" not in body
        assert "nss_encrypted" not in body and "credit_number_encrypted" not in body


def test_listing_never_carries_sensitive_data_not_even_masked(client: TestClient, current_user: CurrentUser):
    _create_with_secrets(client, current_user)

    response = client.get(URL)

    raw = response.text
    assert FAKE_NSS not in raw and FAKE_CREDIT not in raw
    assert NSS_LAST4 not in raw and CREDIT_LAST4 not in raw
    row = response.json()[0]
    assert not any(k for k in row if "nss" in k or "credit" in k)


def test_a_case_without_secrets_reports_null_masks(client: TestClient, current_user: CurrentUser):
    created = client.post(URL, json=_body(current_user)).json()

    assert created["nss_masked"] is None and created["credit_number_masked"] is None


def test_short_secrets_are_fully_masked():
    assert crypto.mask_secret("1234") == "••••"
    assert crypto.mask_secret("012345678") == "•••••5678"
    assert crypto.mask_secret(None) == "••••"


def test_sensitive_input_validation_never_echoes_the_value(client: TestClient, current_user: CurrentUser):
    response = client.post(URL, json=_body(current_user, nss="bad value with spaces!"))

    assert response.status_code == 422
    assert "bad value with spaces" not in response.text


def test_patch_replaces_and_clears_sensitive_values(client: TestClient, current_user: CurrentUser):
    created = _create_with_secrets(client, current_user)

    replaced = client.patch(f"{URL}/{created['id']}", json={"nss": REPLACEMENT_NSS}).json()
    assert replaced["nss_masked"] == mask(REPLACEMENT_NSS)
    assert replaced["credit_number_masked"] == mask(FAKE_CREDIT)  # untouched

    cleared = client.patch(f"{URL}/{created['id']}", json={"credit_number": None}).json()
    assert cleared["credit_number_masked"] is None
    assert cleared["nss_masked"] == mask(REPLACEMENT_NSS)

    untouched = client.patch(f"{URL}/{created['id']}", json={"notes": "solo notas"}).json()
    assert untouched["nss_masked"] == mask(REPLACEMENT_NSS)


# --- encryption not configured ----------------------------------------------------


def test_without_an_encryption_key_sensitive_fields_are_refused_not_stored_in_plaintext(
    client: TestClient, current_user: CurrentUser, db_session: Session, monkeypatch
):
    monkeypatch.setattr(settings, "renova_encryption_key", None)

    response = client.post(URL, json=_body(current_user, nss=FAKE_NSS))

    assert response.status_code == 503
    assert FAKE_NSS not in response.text
    assert db_session.query(RenovaCase).count() == 0  # nothing half-saved


def test_without_a_key_everything_else_still_works(client: TestClient, current_user: CurrentUser, monkeypatch):
    monkeypatch.setattr(settings, "renova_encryption_key", None)

    response = client.post(URL, json=_body(current_user))

    assert response.status_code == 201
    assert response.json()["nss_masked"] is None


def test_a_rotated_away_key_degrades_to_a_bare_mask_instead_of_failing(
    client: TestClient, current_user: CurrentUser, monkeypatch
):
    from cryptography.fernet import Fernet

    created = _create_with_secrets(client, current_user)
    monkeypatch.setattr(settings, "renova_encryption_key", Fernet.generate_key().decode())

    detail = client.get(f"{URL}/{created['id']}")

    assert detail.status_code == 200
    assert detail.json()["nss_masked"] == "••••"


def test_key_rotation_with_multiple_keys_still_decrypts_old_values(
    client: TestClient, current_user: CurrentUser, monkeypatch
):
    from cryptography.fernet import Fernet

    old_key = settings.renova_encryption_key
    created = _create_with_secrets(client, current_user)
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "renova_encryption_key", f"{new_key},{old_key}")

    assert client.get(f"{URL}/{created['id']}").json()["nss_masked"] == mask(FAKE_NSS)


# --- audit -----------------------------------------------------------------------


def _all_audit_json(db_session: Session, case_id: str) -> str:
    rows = db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(case_id)).all()
    return json.dumps([{"b": r.before_data, "a": r.after_data, "act": r.action} for r in rows], default=str)


def test_audit_snapshots_never_contain_sensitive_values_or_even_their_last_four(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    created = _create_with_secrets(client, current_user)
    client.patch(f"{URL}/{created['id']}", json={"nss": REPLACEMENT_NSS, "notes": "edit"})
    client.patch(f"{URL}/{created['id']}", json={"credit_number": None})

    blob = _all_audit_json(db_session, created["id"])

    for secret in (FAKE_NSS, FAKE_CREDIT, REPLACEMENT_NSS, NSS_LAST4, CREDIT_LAST4, "6554"):
        assert secret not in blob
    assert "nss_masked" not in blob and "credit_number_masked" not in blob
    assert "nss_encrypted" not in blob and "credit_number_encrypted" not in blob
    # ciphertext isn't recorded either
    row = db_session.get(RenovaCase, uuid.UUID(created["id"]))
    assert (row.nss_encrypted or "zzz") not in blob


def test_audit_records_that_a_sensitive_field_changed_without_saying_what_it_became(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    created = _create_with_secrets(client, current_user)
    client.patch(f"{URL}/{created['id']}", json={"nss": REPLACEMENT_NSS})

    row = db_session.query(AuditLog).filter(AuditLog.action == "RENOVA_CASE_UPDATED").one()
    assert row.after_data["sensitive_fields_changed"] == ["nss"]
    assert row.before_data["has_nss"] is True and row.after_data["has_nss"] is True


# --- logs & errors ----------------------------------------------------------------


def test_no_log_line_or_error_body_contains_sensitive_values(
    client: TestClient, current_user: CurrentUser, caplog
):
    caplog.set_level(logging.DEBUG)
    created = _create_with_secrets(client, current_user)
    client.get(f"{URL}/{created['id']}")
    client.get(URL)
    client.patch(f"{URL}/{created['id']}", json={"nss": "bad value!"})  # 422
    client.patch(f"{URL}/{uuid.uuid4()}", json={"nss": FAKE_NSS})  # 404

    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (FAKE_NSS, FAKE_CREDIT):
        assert secret not in logged


def test_secretstr_never_prints_the_value():
    from app.schemas.renova_case import RenovaCaseCreate

    data = RenovaCaseCreate(
        assigned_user_id=uuid.uuid4(),
        entry_date="2026-09-20",
        owner_name="X",
        owner_phone="1",
        nss=FAKE_NSS,
        credit_number=FAKE_CREDIT,
    )
    assert FAKE_NSS not in repr(data) and FAKE_CREDIT not in repr(data)
    assert FAKE_NSS not in str(data.model_dump()) and FAKE_CREDIT not in str(data.model_dump())


# --- AI isolation -------------------------------------------------------------------


def test_no_ai_code_references_renova():
    """Agents read LeadContext, which is built only from traditional CRM repositories. Renova is unreachable from any of it."""
    offenders = []
    for path in list((BACKEND_ROOT / "app" / "ai").rglob("*.py")) + [
        BACKEND_ROOT / "app" / "services" / "lead_context_service.py",
        BACKEND_ROOT / "app" / "schemas" / "lead_context.py",
        BACKEND_ROOT / "app" / "ai" / "lead_context_tool.py",
    ]:
        if re.search(r"renova", path.read_text(encoding="utf-8"), re.IGNORECASE):
            offenders.append(str(path.relative_to(BACKEND_ROOT)))
    assert offenders == []


def test_the_agent_registry_and_lead_context_schema_have_no_renova_data():
    from app.ai.registry import AGENT_REGISTRY
    from app.schemas.lead_context import LeadContext

    assert "renova" not in " ".join(AGENT_REGISTRY).lower()
    assert not any("renova" in name.lower() for name in LeadContext.model_fields)


def test_renova_service_does_not_import_the_ai_layer():
    source = (BACKEND_ROOT / "app" / "services" / "renova_case_service.py").read_text(encoding="utf-8")
    assert "app.ai" not in source and "AIGateway" not in source


# --- structural separation from the traditional CRM ----------------------------------


TRADITIONAL_TABLES = {
    "contacts",
    "contact_roles",
    "buyer_requirements",
    "property_interests",
    "opportunities",
    "properties",
}


def test_renova_table_has_no_foreign_key_to_any_traditional_crm_table():
    referred = {fk.column.table.name for fk in RenovaCase.__table__.foreign_keys}
    assert referred == {"organizations", "users"}
    assert referred.isdisjoint(TRADITIONAL_TABLES)


def test_no_traditional_crm_table_references_renova():
    for table in Base.metadata.tables.values():
        if table.name == "renova_cases":
            continue
        assert "renova_cases" not in {fk.column.table.name for fk in table.foreign_keys}


def test_creating_renova_cases_creates_no_contacts_or_other_crm_records(
    client: TestClient, current_user: CurrentUser, db_session: Session
):
    from app.models.buyer_requirement import BuyerRequirement
    from app.models.contact import Contact
    from app.models.opportunity import Opportunity
    from app.models.property import Property
    from app.models.property_interest import PropertyInterest

    _create_with_secrets(client, current_user)

    for model in (Contact, BuyerRequirement, PropertyInterest, Opportunity, Property):
        assert db_session.query(model).count() == 0
    assert client.get("/api/v1/contacts").json() == []


def test_renova_owner_is_not_visible_through_the_contacts_api(client: TestClient, current_user: CurrentUser):
    client.post(URL, json=_body(current_user, owner_name="Soloenrenova Propietaria"))

    assert "Soloenrenova" not in client.get("/api/v1/contacts").text
    assert "Soloenrenova" not in client.get("/api/v1/properties").text


# --- the migration matches the model ----------------------------------------------------


def _load_migration(filename: str = "a7c3e91d5b20_add_renova_cases.py"):
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADDRESS_MIGRATION = "b81f4c2e7a63_add_renova_address_and_occupancy.py"
INE_MIGRATION = "f12a89d7e430_add_renova_ine_images.py"
DUPLEX_MIGRATION = "b2f7a4c9d310_split_renova_duplex_from_dwelling_type.py"


def _render(module, direction: str) -> str:
    """Renders a migration for PostgreSQL as text (offline mode) — no database is touched."""
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer})
    with Operations.context(context):
        getattr(module, direction)()
    return buffer.getvalue()


def _render_upgrade_sql() -> str:
    return _render(_load_migration(), "upgrade")


def test_migration_chain_and_shape():
    module = _load_migration()
    assert module.revision == "a7c3e91d5b20"
    assert module.down_revision == "932767fd7b15"
    sql = _render_upgrade_sql()
    assert sql.count("CREATE TABLE") == 1 and "CREATE TABLE renova_cases" in sql
    # It creates nothing else and alters no existing table.
    assert "ALTER TABLE" not in sql
    for table in TRADITIONAL_TABLES:
        assert f"REFERENCES {table} " not in sql


def test_address_migration_chains_and_only_adds_nullable_columns_to_renova():
    module = _load_migration(ADDRESS_MIGRATION)
    assert module.revision == "b81f4c2e7a63"
    assert module.down_revision == "a7c3e91d5b20"

    sql = _render(module, "upgrade")
    assert sql.count("ALTER TABLE renova_cases ADD COLUMN") == 5
    assert "ALTER TABLE" in sql and sql.count("ALTER TABLE") == 5
    assert "NOT NULL" not in sql and "CREATE TABLE" not in sql and "DROP" not in sql
    for table in TRADITIONAL_TABLES:
        assert table not in sql

    down = _render(module, "downgrade")
    assert down.count("DROP COLUMN") == 5 and "DROP TABLE" not in down


def test_migrations_together_match_the_model():
    sql = (_render_upgrade_sql() + _render(_load_migration(ADDRESS_MIGRATION), "upgrade")
           + _render(_load_migration(INE_MIGRATION), "upgrade")
           + _render(_load_migration(DUPLEX_MIGRATION), "upgrade"))
    table = RenovaCase.__table__

    for column in table.columns:
        created = re.search(rf"^\s+{column.name} ", sql, re.MULTILINE)
        added = f"ADD COLUMN {column.name} " in sql
        assert created or added, f"column {column.name} missing from the migrations"
    for index in table.indexes:
        assert f"CREATE INDEX {index.name} " in sql, f"index {index.name} missing from migration"
    for constraint in table.constraints:
        if constraint.name:
            assert constraint.name in sql, f"constraint {constraint.name} missing from migration"


def test_migration_downgrade_drops_only_renova():
    module = _load_migration()
    sql = _render(module, "downgrade")
    assert "DROP TABLE renova_cases" in sql
    assert sql.count("DROP TABLE") == 1


def test_model_schema_is_creatable_on_the_test_database(db_session: Session):
    inspector = sa_inspect(db_session.get_bind())
    assert "renova_cases" in inspector.get_table_names()
