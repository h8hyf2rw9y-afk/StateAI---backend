"""
Archiving a Renova case (app/models/renova_case.py's `archived`, migration
d4a8e3f61c92): hides it from the default Leads -> Renova list without
deleting it (there is still no delete route). Only ever allowed once a case
has left the purchase flow — status "rejected" or "cancelled" — and cleared
automatically if the case is ever reopened to another status.
"""

import importlib.util
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User
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


def test_defaults_to_not_archived(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)
    assert case["archived"] is False


def test_cannot_archive_a_case_still_in_the_purchase_flow(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)  # status "new"

    response = client.patch(f"{URL}/{case['id']}", json={"archived": True})

    assert response.status_code == 422
    assert client.get(f"{URL}/{case['id']}").json()["archived"] is False


def test_cannot_archive_while_simultaneously_moving_to_an_active_stage(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, status="rejected")

    response = client.patch(f"{URL}/{case['id']}", json={"status": "negotiating", "archived": True})

    assert response.status_code == 422


def test_archiving_a_rejected_case_works(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, status="rejected")

    response = client.patch(f"{URL}/{case['id']}", json={"archived": True})

    assert response.status_code == 200
    assert response.json()["archived"] is True


def test_archiving_a_cancelled_case_works(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)
    client.patch(f"{URL}/{case['id']}", json={"status": "cancelled"})

    response = client.patch(f"{URL}/{case['id']}", json={"archived": True})

    assert response.status_code == 200
    assert response.json()["archived"] is True


def test_can_set_status_and_archived_together_in_one_request(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user)

    response = client.patch(f"{URL}/{case['id']}", json={"status": "cancelled", "archived": True})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled" and body["archived"] is True


def test_archived_cannot_be_explicitly_nulled(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, status="cancelled")

    response = client.patch(f"{URL}/{case['id']}", json={"archived": None})

    assert response.status_code == 422


def test_reopening_a_case_clears_archived_even_without_sending_it(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, status="rejected")
    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    response = client.patch(f"{URL}/{case['id']}", json={"status": "new"})

    assert response.status_code == 200
    assert response.json()["archived"] is False


def test_unarchiving_directly_also_works(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, status="cancelled")
    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    response = client.patch(f"{URL}/{case['id']}", json={"archived": False})

    assert response.status_code == 200
    assert response.json()["archived"] is False


# --- listing -----------------------------------------------------------------


def test_archived_cases_are_hidden_from_the_default_listing(client: TestClient, current_user: CurrentUser):
    visible = _create(client, current_user, owner_name="Visible")
    archived = _create(client, current_user, owner_name="Archivado", status="cancelled")
    client.patch(f"{URL}/{archived['id']}", json={"archived": True})

    default_list = client.get(URL).json()

    assert [c["owner_name"] for c in default_list] == ["Visible"]
    assert client.get(f"{URL}/{archived['id']}").json()["owner_name"] == "Archivado"  # never deleted


def test_explicit_archived_true_shows_only_archived_cases(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Visible")
    archived = _create(client, current_user, owner_name="Archivado", status="cancelled")
    client.patch(f"{URL}/{archived['id']}", json={"archived": True})

    archived_list = client.get(URL, params={"archived": "true"}).json()

    assert [c["owner_name"] for c in archived_list] == ["Archivado"]


def test_explicit_archived_false_is_the_same_as_the_default(client: TestClient, current_user: CurrentUser):
    _create(client, current_user, owner_name="Visible")
    archived = _create(client, current_user, owner_name="Archivado", status="cancelled")
    client.patch(f"{URL}/{archived['id']}", json={"archived": True})

    explicit = client.get(URL, params={"archived": "false"}).json()

    assert [c["owner_name"] for c in explicit] == ["Visible"]


def test_unarchiving_brings_a_case_back_to_the_default_listing(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, owner_name="Va y vuelve", status="cancelled")
    client.patch(f"{URL}/{case['id']}", json={"archived": True})
    assert client.get(URL).json() == []

    client.patch(f"{URL}/{case['id']}", json={"archived": False})

    assert [c["owner_name"] for c in client.get(URL).json()] == ["Va y vuelve"]


# --- audit ---------------------------------------------------------------------


def test_archiving_and_unarchiving_are_each_audited(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create(client, current_user, status="cancelled")

    client.patch(f"{URL}/{case['id']}", json={"archived": True})
    client.patch(f"{URL}/{case['id']}", json={"archived": False})

    actions = _audit_actions(db_session, case["id"])
    assert actions.count("RENOVA_CASE_ARCHIVED") == 1
    assert actions.count("RENOVA_CASE_UNARCHIVED") == 1


def test_reopening_a_case_audits_the_automatic_unarchive(client: TestClient, current_user: CurrentUser, db_session: Session):
    case = _create(client, current_user, status="rejected")
    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    client.patch(f"{URL}/{case['id']}", json={"status": "new"})

    actions = _audit_actions(db_session, case["id"])
    assert actions.count("RENOVA_CASE_UNARCHIVED") == 1


# --- pipeline board never shows an archived (or any rejected/cancelled) case ---


def test_archived_cases_never_appear_on_the_pipeline_board(client: TestClient, current_user: CurrentUser):
    case = _create(client, current_user, status="cancelled")
    client.patch(f"{URL}/{case['id']}", json={"archived": True})

    pipeline = client.get("/api/v1/renova/pipeline").json()

    all_ids = [c["id"] for stage in pipeline["stages"] for c in stage["cases"]]
    assert case["id"] not in all_ids


# --- organization isolation ---------------------------------------------------


def test_an_organization_cannot_archive_another_organizations_case(db_session: Session):
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
        case_b = TestClient(app).post(URL, json=payload(user_b.id, status="cancelled")).json()

        app.dependency_overrides[get_current_org_user] = lambda: cu_a
        response = TestClient(app).patch(f"{URL}/{case_b['id']}", json={"archived": True})

        assert response.status_code == 404
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
    module = _load_migration("d4a8e3f61c92_add_renova_case_archived.py")
    assert module.revision == "d4a8e3f61c92"
    assert module.down_revision == "c9e5f1a72b84"
