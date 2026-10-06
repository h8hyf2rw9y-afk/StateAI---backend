"""
Renova-only advisors (role "renova_agent") inside a shared organization:
each one sees and works only their own Renova cases, never the rest of the
CRM, while the owner/admin keeps seeing everything and manages who has access.
All people and identifiers are synthetic.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.api.routes.renova_chat import get_renova_chat_llm
from app.automation.detectors import _notify_every_org_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_claims, get_current_org_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.organization import Organization, User
from app.models.renova_case import RenovaCase
from app.schemas.user import CurrentUser

URL = "/api/v1/renova/cases"


class FakeChatLLM(LLMProvider):
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-chat"

    def generate_structured(self, *, system_prompt, user_prompt, response_model, max_tokens=1024):
        return response_model.model_validate(self.outputs.pop(0))


def _member(db: Session, organization_id: uuid.UUID, role: str, *, email: str | None = None) -> CurrentUser:
    user_id = uuid.uuid4()
    email = email or f"{role}-{user_id.hex[:6]}@example.com"
    db.add(User(id=user_id, organization_id=organization_id, role=role, email=email))
    db.commit()
    return CurrentUser(id=user_id, email=email, organization_id=organization_id, role=role, provider="google")  # type: ignore[arg-type]


def _case(db: Session, owner: CurrentUser, name: str, **overrides) -> RenovaCase:
    values = {
        "organization_id": owner.organization_id,
        "assigned_user_id": owner.id,
        "created_by_user_id": owner.id,
        "entry_date": date(2026, 9, 20),
        "source": "whatsapp",
        "status": "new",
        "owner_name": name,
        "owner_phone": "81 0000 0000",
        "currency": "MXN",
    }
    values.update(overrides)
    case = RenovaCase(**values)
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _client_as(db: Session, user: CurrentUser) -> TestClient:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user
    return TestClient(app)


def _act_as(user: CurrentUser) -> None:
    app.dependency_overrides[get_current_org_user] = lambda: user


@pytest.fixture()
def team(db_session: Session, organization_id: uuid.UUID):
    """An owner, two Renova advisors, and one case each — plus one case the owner assigned to Ana."""
    owner = _member(db_session, organization_id, "owner", email="dueno@example.com")
    ana = _member(db_session, organization_id, "renova_agent", email="ana@example.com")
    beto = _member(db_session, organization_id, "renova_agent", email="beto@example.com")
    cases = {
        "owner": _case(db_session, owner, "Caso del Dueño"),
        "ana": _case(db_session, ana, "Caso de Ana"),
        "beto": _case(db_session, beto, "Caso de Beto"),
        "assigned_to_ana": _case(db_session, owner, "Asignado a Ana", assigned_user_id=ana.id),
    }
    yield {"owner": owner, "ana": ana, "beto": beto, "cases": cases}
    app.dependency_overrides.clear()


def _names(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {row["owner_name"] for row in response.json()}


# --- what a Renova advisor sees -------------------------------------------------


def test_renova_agent_lists_only_cases_they_created_or_are_assigned(db_session, team):
    client = _client_as(db_session, team["ana"])
    assert _names(client.get(URL, params={"bucket": "active"})) == {"Caso de Ana", "Asignado a Ana"}


def test_renova_agent_cannot_widen_the_list_with_someone_elses_assignee_filter(db_session, team):
    client = _client_as(db_session, team["ana"])
    response = client.get(URL, params={"assigned_user_id": str(team["beto"].id)})
    assert _names(response) == set()


def test_owner_sees_every_case_and_can_filter_by_advisor(db_session, team):
    client = _client_as(db_session, team["owner"])
    assert _names(client.get(URL)) == {"Caso del Dueño", "Caso de Ana", "Caso de Beto", "Asignado a Ana"}
    assert _names(client.get(URL, params={"assigned_user_id": str(team["beto"].id)})) == {"Caso de Beto"}


def test_counts_and_pipeline_are_scoped_to_the_advisor(db_session, team):
    _case(db_session, team["beto"], "Beto cerrado", status="rejected")
    client = _client_as(db_session, team["ana"])

    counts = client.get(f"{URL}/counts").json()
    assert counts["active"] == 2 and counts["closed"] == 0

    board =client.get("/api/v1/renova/pipeline").json()
    on_board = {case["owner_name"] for stage in board["stages"] for case in stage["cases"]}
    assert on_board == {"Caso de Ana", "Asignado a Ana"}


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("patch", "", {"owner_name": "Hackeado"}),
        ("get", "/follow-up", None),
        ("post", "/follow-up", {"activity_type": "call", "result": "no_answer", "occurred_at": "2026-10-01T10:00:00Z"}),
        ("get", "/sensitive-data", None),
        ("get", "/ine/front", None),
    ],
)
def test_another_advisors_case_answers_404_everywhere(db_session, team, method, suffix, body):
    client = _client_as(db_session, team["ana"])
    url = f"{URL}/{team['cases']['beto'].id}{suffix}"
    response = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
    assert response.status_code == 404, response.text


def test_advisor_can_work_their_own_case_end_to_end(db_session, team):
    client = _client_as(db_session, team["ana"])
    case_id = team["cases"]["ana"].id
    assert client.get(f"{URL}/{case_id}").status_code == 200
    assert client.patch(f"{URL}/{case_id}", json={"owner_name": "Caso de Ana (editado)"}).status_code == 200
    follow_up = client.post(
        f"{URL}/{case_id}/follow-up",
        json={"activity_type": "call", "result": "interested", "occurred_at": "2026-10-01T10:00:00Z"},
    )
    assert follow_up.status_code == 201, follow_up.text


def test_advisor_creates_cases_only_for_themselves(db_session, team):
    client = _client_as(db_session, team["ana"])
    base = {"entry_date": "2026-10-01", "owner_name": "Nuevo", "owner_phone": "81 1111 1111"}

    assert client.post(URL, json={**base, "assigned_user_id": str(team["beto"].id)}).status_code == 403
    created = client.post(URL, json={**base, "assigned_user_id": str(team["ana"].id)})
    assert created.status_code == 201, created.text
    assert created.json()["created_by_user_id"] == str(team["ana"].id)


def test_advisor_cannot_hand_a_case_over_to_someone_else(db_session, team):
    client = _client_as(db_session, team["ana"])
    response = client.patch(f"{URL}/{team['cases']['ana'].id}", json={"assigned_user_id": str(team["beto"].id)})
    assert response.status_code == 403


def test_owner_can_reassign_a_case_to_an_advisor(db_session, team):
    client = _client_as(db_session, team["owner"])
    response = client.patch(f"{URL}/{team['cases']['owner'].id}", json={"assigned_user_id": str(team["beto"].id)})
    assert response.status_code == 200
    _act_as(team["beto"])
    assert "Caso del Dueño" in _names(client.get(URL))


def test_renova_chat_only_counts_and_finds_the_advisors_own_cases(db_session, team):
    llm = FakeChatLLM([
        {"intent": "active_count"},
        {"intent": "status", "owner_name": "Caso de Beto"},
    ])
    client = _client_as(db_session, team["ana"])
    app.dependency_overrides[get_renova_chat_llm] = lambda: llm
    conversation = client.post("/api/v1/renova/chat/conversations", json={}).json()["id"]
    messages = f"/api/v1/renova/chat/conversations/{conversation}/messages"

    count = client.post(messages, json={"content": "¿Cuántos leads activos tengo?"})
    assert count.status_code == 200, count.text
    assert "2 leads activos" in count.json()["assistant_message"]["content"]

    other = client.post(messages, json={"content": "¿En qué etapa va Caso de Beto?"})
    assert other.status_code == 404


# --- the rest of the CRM ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/v1/contacts", "/api/v1/properties", "/api/v1/opportunities", "/api/v1/tasks",
     "/api/v1/appointments", "/api/v1/notifications", "/api/v1/audit-logs"],
)
def test_renova_agent_is_refused_by_every_crm_route(db_session, team, path):
    client = _client_as(db_session, team["ana"])
    response = client.get(path)
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "This account only has access to the Renova module."


def test_renova_agent_can_still_read_me_and_their_organization(db_session, team):
    client = _client_as(db_session, team["ana"])
    assert client.get("/api/v1/me").json()["role"] == "renova_agent"
    assert client.get("/api/v1/organization").status_code == 200


def test_crm_notifications_skip_renova_agents_and_deactivated_accounts(db_session, team, organization_id):
    db_session.add(User(id=uuid.uuid4(), organization_id=organization_id, role="agent", is_active=False))
    db_session.commit()
    created = _notify_every_org_user(
        db_session,
        organization_id,
        notification_type="contact_missing_requirement",
        title="t",
        body="b",
        related_entity_type="contact",
        related_entity_id=uuid.uuid4(),
    )
    assert {n.user_id for n in created} == {team["owner"].id}
    assert db_session.query(Notification).count() == 1


# --- admin: members ---------------------------------------------------------------


def test_owner_lists_members_with_email_role_and_case_counts(db_session, team):
    client = _client_as(db_session, team["owner"])
    response = client.get("/api/v1/organization/members")
    assert response.status_code == 200, response.text
    rows = {row["email"]: row for row in response.json()}
    assert response.json()[0]["role"] == "owner"
    assert rows["ana@example.com"]["role"] == "renova_agent"
    assert rows["ana@example.com"]["renova_cases"] == {"active": 2, "closed": 0, "archived": 0}
    assert rows["beto@example.com"]["renova_cases"]["active"] == 1


@pytest.mark.parametrize("role", ["agent", "renova_agent"])
def test_non_admins_cannot_list_or_change_members(db_session, team, organization_id, role):
    user = team["ana"] if role == "renova_agent" else _member(db_session, organization_id, "agent")
    client = _client_as(db_session, user)
    assert client.get("/api/v1/organization/members").status_code == 403
    assert client.patch(f"/api/v1/organization/members/{team['beto'].id}", json={"is_active": False}).status_code == 403


def test_owner_deactivates_and_reactivates_an_advisor_with_audit(db_session, team):
    client = _client_as(db_session, team["owner"])
    url = f"/api/v1/organization/members/{team['ana'].id}"

    off = client.patch(url, json={"is_active": False})
    assert off.status_code == 200, off.text
    assert off.json()["is_active"] is False and off.json()["deactivated_at"] is not None
    on = client.patch(url, json={"is_active": True})
    assert on.json()["is_active"] is True and on.json()["deactivated_at"] is None

    actions = [row.action for row in db_session.query(AuditLog).filter(AuditLog.entity_id == team["ana"].id)]
    assert actions == ["USER_DEACTIVATED", "USER_REACTIVATED"]
    # Their cases are untouched.
    assert db_session.get(RenovaCase, team["cases"]["ana"].id) is not None


def test_nobody_deactivates_themselves_or_the_owner(db_session, team, organization_id):
    owner_client = _client_as(db_session, team["owner"])
    assert owner_client.patch(f"/api/v1/organization/members/{team['owner'].id}", json={"is_active": False}).status_code == 409

    admin = _member(db_session, organization_id, "admin")
    _act_as(admin)
    assert owner_client.patch(f"/api/v1/organization/members/{team['owner'].id}", json={"is_active": False}).status_code == 403
    other_admin = _member(db_session, organization_id, "admin")
    assert owner_client.patch(f"/api/v1/organization/members/{other_admin.id}", json={"is_active": False}).status_code == 403
    assert owner_client.patch(f"/api/v1/organization/members/{team['ana'].id}", json={"is_active": False}).status_code == 200


def test_members_of_another_organization_are_not_found(db_session, team):
    other_org = Organization(name="Otra")
    db_session.add(other_org)
    db_session.commit()
    stranger = _member(db_session, other_org.id, "renova_agent")
    client = _client_as(db_session, team["owner"])
    assert client.patch(f"/api/v1/organization/members/{stranger.id}", json={"is_active": False}).status_code == 404
    assert stranger.email not in {row["email"] for row in client.get("/api/v1/organization/members").json()}


# --- authentication-level behavior (real get_current_org_user, faked claims) ----


def _claims_client(db: Session, user_id: uuid.UUID, email: str) -> TestClient:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: {"sub": str(user_id), "email": email, "app_metadata": {"provider": "google"}}
    return TestClient(app)


def test_a_deactivated_account_is_refused_even_with_a_valid_session(db_session, organization_id):
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, organization_id=organization_id, role="renova_agent", is_active=False))
    db_session.commit()
    client = _claims_client(db_session, user_id, "baja@example.com")
    try:
        response = client.get("/api/v1/me")
        assert response.status_code == 403
        assert response.json()["error"]["message"] == "This account has been deactivated."
    finally:
        app.dependency_overrides.clear()


def test_invitation_as_renova_agent_stores_the_email_on_accept(db_session, team):
    owner_client = _client_as(db_session, team["owner"])
    invitation = owner_client.post(
        "/api/v1/organization/invitations", json={"email": "Nueva.Asesora@Gmail.com", "role": "renova_agent"}
    )
    assert invitation.status_code == 201, invitation.text
    app.dependency_overrides.clear()

    new_id = uuid.uuid4()
    client = _claims_client(db_session, new_id, "nueva.asesora@gmail.com")
    try:
        joined = client.post("/api/v1/me/organization/join", json={"token": invitation.json()["token"]})
        assert joined.status_code == 200, joined.text
        assert joined.json()["role"] == "renova_agent"
        assert db_session.get(User, new_id).email == "nueva.asesora@gmail.com"
    finally:
        app.dependency_overrides.clear()


def test_invitation_only_mode_refuses_to_create_new_organizations(db_session, monkeypatch, organization_id):
    monkeypatch.setattr(settings, "allow_self_service_signup", False)
    stranger = uuid.uuid4()
    client = _claims_client(db_session, stranger, "desconocido@gmail.com")
    try:
        response = client.post("/api/v1/me/organization", json={})
        assert response.status_code == 403
        assert db_session.get(User, stranger) is None
        assert db_session.query(Organization).count() == 1

        # Someone already provisioned keeps signing in normally.
        existing = uuid.uuid4()
        db_session.add(User(id=existing, organization_id=organization_id, role="renova_agent"))
        db_session.commit()
        app.dependency_overrides[get_current_claims] = lambda: {"sub": str(existing), "email": "ya@x.com"}
        assert client.post("/api/v1/me/organization", json={}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_self_service_signup_still_stores_the_owners_email(db_session):
    new_id = uuid.uuid4()
    client = _claims_client(db_session, new_id, "Owner@Example.com")
    try:
        assert client.post("/api/v1/me/organization", json={}).status_code == 200
        assert db_session.get(User, new_id).email == "owner@example.com"
    finally:
        app.dependency_overrides.clear()
