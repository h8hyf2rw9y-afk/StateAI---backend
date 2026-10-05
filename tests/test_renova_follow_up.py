import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import Organization, User
from app.schemas.user import CurrentUser

URL = "/api/v1/renova/cases"


def create_case(client: TestClient, current_user: CurrentUser, name: str = "Mercedes Cortez") -> dict:
    response = client.post(
        URL,
        json={
            "assigned_user_id": str(current_user.id),
            "entry_date": "2026-10-01",
            "owner_name": name,
            "owner_phone": "8112345678",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_list_defaults_to_never_contacted(client, current_user):
    case = create_case(client, current_user)

    row = client.get(URL).json()[0]

    assert row["id"] == case["id"]
    assert row["follow_up"] == {
        "last_call_activity_id": None,
        "last_call_at": None,
        "last_result": None,
        "contact_attempt_count": 0,
        "next_follow_up_at": None,
        "is_follow_up_overdue": False,
        "contact_state": "never_contacted",
        "note_preview": None,
    }


def test_historical_call_sets_editable_last_call_result_and_attempt_baseline(client, current_user):
    case = create_case(client, current_user)
    occurred = datetime.now(timezone.utc) - timedelta(days=4)

    response = client.post(
        f"{URL}/{case['id']}/follow-up",
        json={
            "activity_type": "call",
            "result": "no_answer",
            "occurred_at": occurred.isoformat(),
            "attempt_number": 2,
            "notes": "Segundo intento por la tarde.",
        },
    )

    assert response.status_code == 201, response.text
    summary = response.json()["summary"]
    assert summary["last_result"] == "no_answer"
    assert summary["contact_attempt_count"] == 2
    assert summary["contact_state"] == "attempted_no_answer"
    assert summary["note_preview"] == "Segundo intento por la tarde."


def test_new_call_increments_from_historical_attempt_number(client, current_user):
    case = create_case(client, current_user)
    base = datetime.now(timezone.utc) - timedelta(days=2)
    client.post(
        f"{URL}/{case['id']}/follow-up",
        json={"activity_type": "call", "result": "no_answer", "occurred_at": base.isoformat(), "attempt_number": 3},
    )

    response = client.post(
        f"{URL}/{case['id']}/follow-up",
        json={"activity_type": "call", "result": "interested", "occurred_at": datetime.now(timezone.utc).isoformat()},
    )

    assert response.status_code == 201
    assert response.json()["summary"]["contact_attempt_count"] == 4
    assert response.json()["summary"]["last_result"] == "interested"


def test_schedule_and_edit_last_call(client, current_user):
    case = create_case(client, current_user)
    call = client.post(
        f"{URL}/{case['id']}/follow-up",
        json={"activity_type": "call", "result": "no_answer", "occurred_at": datetime.now(timezone.utc).isoformat(), "attempt_number": 2},
    ).json()
    call_id = call["summary"]["last_call_activity_id"]
    scheduled = datetime.now(timezone.utc) + timedelta(days=1)

    schedule_response = client.post(
        f"{URL}/{case['id']}/follow-up",
        json={
            "activity_type": "follow_up",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "next_follow_up_at": scheduled.isoformat(),
            "notes": "Confirmar si desea continuar.",
        },
    )
    assert schedule_response.status_code == 201
    assert schedule_response.json()["summary"]["next_follow_up_at"] is not None

    edit_response = client.patch(
        f"{URL}/{case['id']}/follow-up/{call_id}",
        json={"result": "callback_requested", "attempt_number": 5, "notes": "Pidió llamada posterior."},
    )
    assert edit_response.status_code == 200, edit_response.text
    summary = edit_response.json()["summary"]
    assert summary["last_result"] == "callback_requested"
    assert summary["contact_attempt_count"] == 5
    assert summary["note_preview"] == "Pidió llamada posterior."


def test_overdue_schedule_is_derived(client, current_user):
    case = create_case(client, current_user)
    response = client.post(
        f"{URL}/{case['id']}/follow-up",
        json={
            "activity_type": "follow_up",
            "occurred_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            "next_follow_up_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        },
    )
    assert response.json()["summary"]["is_follow_up_overdue"] is True


def test_a_later_call_without_another_date_clears_the_old_schedule(client, current_user):
    case = create_case(client, current_user)
    now = datetime.now(timezone.utc)
    client.post(
        f"{URL}/{case['id']}/follow-up",
        json={
            "activity_type": "follow_up",
            "occurred_at": (now - timedelta(hours=1)).isoformat(),
            "next_follow_up_at": (now + timedelta(days=1)).isoformat(),
        },
    )

    response = client.post(
        f"{URL}/{case['id']}/follow-up",
        json={"activity_type": "call", "result": "interested", "occurred_at": now.isoformat()},
    )

    assert response.status_code == 201
    assert response.json()["summary"]["next_follow_up_at"] is None
    assert response.json()["summary"]["is_follow_up_overdue"] is False


def test_follow_up_is_tenant_isolated(client, db_session, current_user):
    case = create_case(client, current_user)
    other_org = Organization(name="Other")
    db_session.add(other_org)
    db_session.flush()
    other_user_id = uuid.uuid4()
    db_session.add(User(id=other_user_id, organization_id=other_org.id, role="agent"))
    db_session.commit()
    other_user = CurrentUser(
        id=other_user_id,
        email="other@example.com",
        organization_id=other_org.id,
        role="agent",
        provider="email",
    )
    app.dependency_overrides[get_current_org_user] = lambda: other_user

    assert client.get(f"{URL}/{case['id']}/follow-up").status_code == 404
    assert client.post(
        f"{URL}/{case['id']}/follow-up",
        json={"activity_type": "call", "result": "no_answer", "occurred_at": datetime.now(timezone.utc).isoformat()},
    ).status_code == 404
