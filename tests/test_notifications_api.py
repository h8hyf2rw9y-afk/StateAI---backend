"""
Notifications (app/models/notification.py): personal ownership (not just
organization scoping — another org member must not read or mark someone
else's notification), listing, unread filtering, and marking read.

There is no POST /notifications route (see app/api/routes/notifications.py)
— notifications are created by NotificationService directly, exercised here
the same way a future internal caller (e.g. a scheduled job, once one
exists) would.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.notification import NotificationCreate
from app.schemas.user import CurrentUser
from app.services.notification_service import NotificationService


def _create_notification(db_session: Session, organization_id, user_id, **overrides) -> dict:
    fields = {
        "user_id": user_id,
        "type": "task_due",
        "title": "Task due soon",
        "body": "Llamar a Juan vence hoy.",
    }
    fields.update(overrides)
    notification = NotificationService(db_session).create(organization_id, NotificationCreate(**fields))
    return {"id": str(notification.id)}


def test_list_my_notifications(client: TestClient, db_session: Session, current_user: CurrentUser):
    _create_notification(db_session, current_user.organization_id, current_user.id)

    listed = client.get("/api/v1/notifications").json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Task due soon"
    assert listed[0]["read_at"] is None


def test_unread_filter(client: TestClient, db_session: Session, current_user: CurrentUser):
    read_one = _create_notification(db_session, current_user.organization_id, current_user.id, title="Read")
    _create_notification(db_session, current_user.organization_id, current_user.id, title="Unread")
    client.patch(f"/api/v1/notifications/{read_one['id']}", json={"read": True})

    unread = client.get("/api/v1/notifications", params={"unread": "true"}).json()
    assert [n["title"] for n in unread] == ["Unread"]


def test_mark_notification_read_and_unread(client: TestClient, db_session: Session, current_user: CurrentUser):
    notification = _create_notification(db_session, current_user.organization_id, current_user.id)

    marked = client.patch(f"/api/v1/notifications/{notification['id']}", json={"read": True})
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None

    unmarked = client.patch(f"/api/v1/notifications/{notification['id']}", json={"read": False})
    assert unmarked.status_code == 200
    assert unmarked.json()["read_at"] is None


def test_a_user_cannot_read_or_mark_another_users_notification(
    client: TestClient, db_session: Session, current_user: CurrentUser
):
    """Ownership, not just organization scoping — see NotificationService.get_or_404_for_user."""
    from app.models.organization import User

    other_user = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(other_user)
    db_session.commit()

    others_notification = _create_notification(db_session, current_user.organization_id, other_user.id)

    assert client.get("/api/v1/notifications").json() == []  # current_user's own list never shows it
    response = client.patch(f"/api/v1/notifications/{others_notification['id']}", json={"read": True})
    assert response.status_code == 404


def test_notifications_are_isolated_by_organization(db_session: Session):
    from app.models.organization import Organization, User

    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()
    user_b = User(id=uuid.uuid4(), organization_id=org_b.id, role="agent")
    db_session.add(user_b)
    db_session.commit()

    _create_notification(db_session, org_b.id, user_b.id)

    from app.core.database import get_db
    from app.core.security import get_current_org_user
    from app.main import app

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        assert client_a.get("/api/v1/notifications").json() == []
    finally:
        app.dependency_overrides.clear()
