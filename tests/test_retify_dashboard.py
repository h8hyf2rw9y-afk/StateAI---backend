import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import User
from app.models.renova_case import RenovaCase
from app.models.renova_follow_up import RenovaFollowUpActivity
from app.schemas.user import CurrentUser

URL = "/api/v1/organization/retify-dashboard"


def _user(db, organization_id, role, email):
    user = User(id=uuid.uuid4(), organization_id=organization_id, role=role, email=email)
    db.add(user)
    db.commit()
    return user


def _case(db, organization_id, assignee, name, **overrides):
    values = {"organization_id": organization_id, "assigned_user_id": assignee.id, "created_by_user_id": assignee.id, "entry_date": date.today(), "source": "whatsapp", "status": "new", "owner_name": name, "owner_phone": "8112345678"}
    values.update(overrides)
    case = RenovaCase(**values)
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _client_as(db, user):
    def override_db():
        yield db
    def override_user():
        return CurrentUser(id=user.id, email=user.email, organization_id=user.organization_id, role=user.role, provider="email")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_org_user] = override_user
    return TestClient(app)


def test_owner_gets_team_metrics_attention_and_advisor_filter(db_session, organization_id):
    owner = _user(db_session, organization_id, "owner", "owner@example.com")
    ana = _user(db_session, organization_id, "renova_agent", "ana@example.com")
    beto = _user(db_session, organization_id, "renova_agent", "beto@example.com")
    stale = _case(db_session, organization_id, ana, "Nuevo olvidado")
    stale.created_at = datetime.now(timezone.utc) - timedelta(days=4)
    negotiating = _case(db_session, organization_id, ana, "En negociación", status="negotiating")
    _case(db_session, organization_id, beto, "Aceptado", status="accepted", operation_stage="site_survey")
    _case(db_session, organization_id, beto, "Archivado", status="rejected", archived=True)
    db_session.add(RenovaFollowUpActivity(organization_id=organization_id, renova_case_id=negotiating.id, actor_user_id=ana.id, activity_type="call", result="no_answer", occurred_at=datetime.now(timezone.utc) - timedelta(days=4), attempt_number=1))
    db_session.commit()

    response = _client_as(db_session, owner).get(URL, params={"period": "30d"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == {"received": 4, "active": 3, "closed": 0, "archived": 1, "contacted": 1, "no_answer": 1, "follow_ups_overdue": 0, "proposals_sent": 2, "negotiating": 1, "accepted": 1, "operations_open": 1, "operations_closed": 0, "conversion_rate": 25.0}
    assert {row["email"] for row in body["advisors"]} == {"owner@example.com", "ana@example.com", "beto@example.com"}
    assert [item["owner_name"] for item in body["attention"]] == ["Nuevo olvidado", "En negociación"]
    filtered = _client_as(db_session, owner).get(URL, params={"period": "all", "assigned_user_id": str(ana.id)})
    assert filtered.json()["summary"]["received"] == 2
    assert [row["email"] for row in filtered.json()["advisors"]] == ["ana@example.com"]


def test_dashboard_is_owner_admin_only_and_does_not_leak_other_organizations(db_session, organization_id):
    advisor = _user(db_session, organization_id, "renova_agent", "advisor@example.com")
    assert _client_as(db_session, advisor).get(URL).status_code == 403
    owner = _user(db_session, organization_id, "owner", "owner@example.com")
    response = _client_as(db_session, owner).get(URL, params={"assigned_user_id": str(uuid.uuid4())})
    assert response.status_code == 200
    assert response.json()["summary"]["received"] == 0
    assert response.json()["advisors"] == []


def test_normal_admin_can_read_complete_retify_dashboard(db_session, organization_id):
    admin = _user(db_session, organization_id, "admin", "admin@example.com")
    advisor = _user(db_session, organization_id, "renova_agent", "advisor@example.com")
    _case(db_session, organization_id, advisor, "Visible para admin")
    response = _client_as(db_session, admin).get(URL)
    assert response.status_code == 200
    assert response.json()["summary"]["received"] == 1
