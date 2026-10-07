"""
Bringing a specific person into an EXISTING organization
(app/services/organization_invitation_service.py, app/api/routes/
organization.py, POST /me/organization/join) — as opposed to
app/services/onboarding_service.py, which always creates a brand-new one.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_claims, get_current_org_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User
from app.models.organization_invitation import OrganizationInvitation
from app.schemas.user import CurrentUser

ORGANIZATION_URL = "/api/v1/organization"
INVITATIONS_URL = "/api/v1/organization/invitations"
JOIN_URL = "/api/v1/me/organization/join"


def _claims(user_id: uuid.UUID, *, email: str | None = "new.agent@example.com") -> dict:
    return {"sub": str(user_id), "email": email, "user_metadata": {}, "app_metadata": {"provider": "email"}}


def _unprovisioned_client(db_session: Session, claims: dict) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: claims
    return TestClient(app)


def _public_client(db_session: Session) -> TestClient:
    """For the one route with no auth dependency at all (preview) — still needs `get_db` pointed at the test's own in-memory database, not whatever `get_db` would otherwise resolve to."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _org_client(db_session: Session, *, role: str) -> tuple[TestClient, CurrentUser]:
    """A fresh organization with one user of the given role, wired as the authenticated caller."""
    org = Organization(name="Invite Test Realty")
    db_session.add(org)
    db_session.flush()
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, organization_id=org.id, role=role))
    db_session.commit()
    current = CurrentUser(id=user_id, email=f"{role}@example.com", organization_id=org.id, role=role, provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: current
    return TestClient(app), current


def _create_invitation(client: TestClient, email: str = "colega@example.com", role: str = "agent") -> dict:
    response = client.post(INVITATIONS_URL, json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


# --- organization info -----------------------------------------------------------


def test_any_org_member_can_read_their_organization_name(db_session: Session):
    agent_client, _ = _org_client(db_session, role="agent")
    try:
        response = agent_client.get(ORGANIZATION_URL)
        assert response.status_code == 200
        assert response.json()["name"] == "Invite Test Realty"
    finally:
        app.dependency_overrides.clear()


def test_reading_organization_requires_authentication():
    assert TestClient(app).get(ORGANIZATION_URL).status_code == 401


# --- creating ------------------------------------------------------------------


def test_agent_cannot_create_an_invitation(client: TestClient, current_user: CurrentUser):
    assert current_user.role == "agent"
    response = client.post(INVITATIONS_URL, json={"email": "colega@example.com"})
    assert response.status_code == 403


def test_owner_can_create_an_invitation(db_session: Session):
    owner_client, owner = _org_client(db_session, role="owner")
    try:
        body = _create_invitation(owner_client)
        assert body["email"] == "colega@example.com"
        assert body["role"] == "agent"
        assert body["status"] == "pending"
        assert len(body["token"]) > 20
    finally:
        app.dependency_overrides.clear()


def test_admin_can_create_an_advisor_invitation(db_session: Session):
    admin_client, _ = _org_client(db_session, role="admin")
    try:
        response = admin_client.post(
            INVITATIONS_URL, json={"email": "colega@example.com", "role": "renova_agent"}
        )
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()


def test_email_is_normalized_to_lowercase(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        body = _create_invitation(owner_client, email="Colega@Example.COM")
        assert body["email"] == "colega@example.com"
    finally:
        app.dependency_overrides.clear()


def test_cannot_invite_someone_as_owner(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        response = owner_client.post(INVITATIONS_URL, json={"email": "colega@example.com", "role": "owner"})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_creating_an_invitation_is_audited(db_session: Session):
    owner_client, owner = _org_client(db_session, role="owner")
    try:
        body = _create_invitation(owner_client)
        entries = db_session.query(AuditLog).filter(AuditLog.entity_id == uuid.UUID(body["id"])).all()
        assert len(entries) == 1
        assert entries[0].action == "ORGANIZATION_INVITATION_CREATED"
        assert entries[0].actor_user_id == owner.id
    finally:
        app.dependency_overrides.clear()


# --- listing / revoking ----------------------------------------------------------


def test_agent_cannot_list_invitations(client: TestClient):
    assert client.get(INVITATIONS_URL).status_code == 403


def test_list_never_includes_the_token(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        _create_invitation(owner_client)
        rows = owner_client.get(INVITATIONS_URL).json()
        assert len(rows) == 1
        assert "token" not in rows[0]
    finally:
        app.dependency_overrides.clear()


def test_revoking_a_pending_invitation(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        invitation = _create_invitation(owner_client)
        response = owner_client.delete(f"{INVITATIONS_URL}/{invitation['id']}")
        assert response.status_code == 204
        rows = owner_client.get(INVITATIONS_URL).json()
        assert rows[0]["status"] == "revoked"
    finally:
        app.dependency_overrides.clear()


def test_revoking_an_already_revoked_invitation_is_rejected(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        invitation = _create_invitation(owner_client)
        owner_client.delete(f"{INVITATIONS_URL}/{invitation['id']}")
        response = owner_client.delete(f"{INVITATIONS_URL}/{invitation['id']}")
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_cannot_revoke_another_organizations_invitation(db_session: Session):
    owner_a_client, _ = _org_client(db_session, role="owner")
    invitation = _create_invitation(owner_a_client)
    app.dependency_overrides.clear()

    owner_b_client, _ = _org_client(db_session, role="owner")
    try:
        response = owner_b_client.delete(f"{INVITATIONS_URL}/{invitation['id']}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# --- preview (public) --------------------------------------------------------------


def test_preview_of_a_valid_invitation_shows_the_organization_name(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        invitation = _create_invitation(owner_client)

        preview = _public_client(db_session).get(f"{INVITATIONS_URL}/preview/{invitation['token']}")
        assert preview.status_code == 200
        body = preview.json()
        assert body["valid"] is True
        assert body["organization_name"] == "Invite Test Realty"
    finally:
        app.dependency_overrides.clear()


def test_preview_of_an_unknown_token_is_invalid(db_session: Session):
    response = _public_client(db_session).get(f"{INVITATIONS_URL}/preview/not-a-real-token")
    assert response.status_code == 200
    assert response.json() == {"valid": False, "organization_name": None}


def test_preview_of_a_revoked_invitation_is_invalid(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        invitation = _create_invitation(owner_client)
        owner_client.delete(f"{INVITATIONS_URL}/{invitation['id']}")

        preview = _public_client(db_session).get(f"{INVITATIONS_URL}/preview/{invitation['token']}")
        assert preview.json()["valid"] is False
    finally:
        app.dependency_overrides.clear()


def test_preview_of_an_expired_invitation_is_invalid(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    try:
        invitation = _create_invitation(owner_client)
        row = db_session.get(OrganizationInvitation, uuid.UUID(invitation["id"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()

        preview = _public_client(db_session).get(f"{INVITATIONS_URL}/preview/{invitation['token']}")
        assert preview.json()["valid"] is False
    finally:
        app.dependency_overrides.clear()


# --- accepting / joining -----------------------------------------------------------


def test_accepting_joins_the_inviters_organization(db_session: Session):
    owner_client, owner = _org_client(db_session, role="owner")
    invitation = _create_invitation(owner_client, email="nueva@example.com", role="agent")
    app.dependency_overrides.clear()

    new_user_id = uuid.uuid4()
    joiner = _unprovisioned_client(db_session, _claims(new_user_id, email="nueva@example.com"))
    try:
        response = joiner.post(JOIN_URL, json={"token": invitation["token"]})
        assert response.status_code == 200
        body = response.json()
        assert body["organization_id"] == str(owner.organization_id)
        assert body["role"] == "agent"
    finally:
        app.dependency_overrides.clear()


def test_accepting_requires_the_invited_email(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    invitation = _create_invitation(owner_client, email="nueva@example.com")
    app.dependency_overrides.clear()

    new_user_id = uuid.uuid4()
    joiner = _unprovisioned_client(db_session, _claims(new_user_id, email="alguien.mas@example.com"))
    try:
        response = joiner.post(JOIN_URL, json={"token": invitation["token"]})
        assert response.status_code == 403
        assert db_session.get(User, new_user_id) is None
    finally:
        app.dependency_overrides.clear()


def test_accepting_an_unknown_or_expired_token_is_rejected(db_session: Session):
    new_user_id = uuid.uuid4()
    joiner = _unprovisioned_client(db_session, _claims(new_user_id))
    try:
        response = joiner.post(JOIN_URL, json={"token": "not-a-real-token"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_accepting_twice_is_idempotent(db_session: Session):
    owner_client, owner = _org_client(db_session, role="owner")
    invitation = _create_invitation(owner_client, email="nueva@example.com")
    app.dependency_overrides.clear()

    new_user_id = uuid.uuid4()
    joiner = _unprovisioned_client(db_session, _claims(new_user_id, email="nueva@example.com"))
    try:
        first = joiner.post(JOIN_URL, json={"token": invitation["token"]})
        second = joiner.post(JOIN_URL, json={"token": invitation["token"]})
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["organization_id"] == second.json()["organization_id"] == str(owner.organization_id)
        assert db_session.query(User).filter(User.id == new_user_id).count() == 1
    finally:
        app.dependency_overrides.clear()


def test_accepting_while_already_in_a_different_organization_is_rejected(db_session: Session):
    # The joiner already self-provisioned into their OWN organization earlier.
    existing_client, existing = _org_client(db_session, role="owner")
    other_org_id = existing.organization_id
    app.dependency_overrides.clear()

    owner_client, _ = _org_client(db_session, role="owner")
    invitation = _create_invitation(owner_client, email="ya.tiene.cuenta@example.com")
    app.dependency_overrides.clear()

    joiner = _unprovisioned_client(
        db_session, _claims(existing.id, email="ya.tiene.cuenta@example.com")
    )
    try:
        response = joiner.post(JOIN_URL, json={"token": invitation["token"]})
        assert response.status_code == 409
        assert db_session.get(User, existing.id).organization_id == other_org_id
    finally:
        app.dependency_overrides.clear()


def test_accepting_marks_the_invitation_accepted_and_audits(db_session: Session):
    owner_client, _ = _org_client(db_session, role="owner")
    invitation = _create_invitation(owner_client, email="nueva@example.com")
    app.dependency_overrides.clear()

    new_user_id = uuid.uuid4()
    joiner = _unprovisioned_client(db_session, _claims(new_user_id, email="nueva@example.com"))
    try:
        joiner.post(JOIN_URL, json={"token": invitation["token"]})
    finally:
        app.dependency_overrides.clear()

    row = db_session.get(OrganizationInvitation, uuid.UUID(invitation["id"]))
    assert row.status == "accepted"
    assert row.accepted_by_user_id == new_user_id
    assert row.accepted_at is not None
    actions = [a.action for a in db_session.query(AuditLog).filter(AuditLog.entity_id == row.id).all()]
    assert "ORGANIZATION_INVITATION_ACCEPTED" in actions


def test_join_requires_authentication():
    response = TestClient(app).post(JOIN_URL, json={"token": "whatever"})
    assert response.status_code == 401


# --- migration -----------------------------------------------------------------


def _load_migration(filename: str):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chain():
    module = _load_migration("afb09875036b_add_organization_invitations.py")
    assert module.revision == "afb09875036b"
    assert module.down_revision == "d4f7a9c21b31"
