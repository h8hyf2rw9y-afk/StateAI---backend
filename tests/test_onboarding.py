"""
Self-service onboarding (POST /me/organization) — turns a real, verified,
but unprovisioned Supabase session into a usable, org-scoped account. See
app/core/security.get_current_org_user's 403 branch and
app/services/onboarding_service.py.

This route deliberately does NOT depend on get_current_org_user (that's
exactly the dependency that 403s for the caller it exists to help), so the
`client` fixture's usual get_current_org_user override doesn't apply here —
every test below overrides get_current_claims directly instead, the same
way tests/test_lead_context.py's cross-org test does for a similar reason.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User


def _claims(user_id: uuid.UUID, *, email: str | None = "new.agent@example.com", user_metadata: dict | None = None) -> dict:
    return {
        "sub": str(user_id),
        "email": email,
        "user_metadata": user_metadata or {},
        "app_metadata": {"provider": "email"},
    }


def _client_as(db_session: Session, claims: dict) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: claims
    return TestClient(app)


def test_provision_creates_a_new_organization_and_owner_user(db_session: Session):
    user_id = uuid.uuid4()
    client = _client_as(db_session, _claims(user_id, user_metadata={"first_name": "Ana", "last_name": "Reyes"}))
    try:
        response = client.post("/api/v1/me/organization")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(user_id)
        assert body["role"] == "owner"
        assert uuid.UUID(body["organization_id"])

        user_row = db_session.get(User, user_id)
        assert user_row is not None
        assert user_row.role == "owner"
        organization = db_session.get(Organization, user_row.organization_id)
        assert organization is not None
        assert organization.name == "Ana Reyes's Organization"
    finally:
        app.dependency_overrides.clear()


def test_provision_falls_back_to_email_when_no_name_metadata(db_session: Session):
    user_id = uuid.uuid4()
    client = _client_as(db_session, _claims(user_id, email="solo.agent@example.com", user_metadata={}))
    try:
        response = client.post("/api/v1/me/organization")
        assert response.status_code == 200
        user_row = db_session.get(User, user_id)
        organization = db_session.get(Organization, user_row.organization_id)
        assert organization.name == "solo.agent@example.com's Organization"
    finally:
        app.dependency_overrides.clear()


def test_provision_accepts_an_explicit_name_override(db_session: Session):
    user_id = uuid.uuid4()
    client = _client_as(db_session, _claims(user_id, user_metadata={"first_name": "Ana"}))
    try:
        response = client.post("/api/v1/me/organization", json={"name": "Reyes Realty Group"})
        assert response.status_code == 200
        user_row = db_session.get(User, user_id)
        organization = db_session.get(Organization, user_row.organization_id)
        assert organization.name == "Reyes Realty Group"
    finally:
        app.dependency_overrides.clear()


def test_provision_is_idempotent_never_creates_a_second_organization(db_session: Session):
    user_id = uuid.uuid4()
    client = _client_as(db_session, _claims(user_id, user_metadata={"first_name": "Ana", "last_name": "Reyes"}))
    try:
        first = client.post("/api/v1/me/organization")
        second = client.post("/api/v1/me/organization")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["organization_id"] == second.json()["organization_id"]

        organizations = db_session.query(Organization).all()
        assert len(organizations) == 1
        users = db_session.query(User).filter(User.id == user_id).all()
        assert len(users) == 1
    finally:
        app.dependency_overrides.clear()


def test_two_different_signups_get_two_different_organizations(db_session: Session):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    client_a = _client_as(db_session, _claims(user_a, email="a@example.com", user_metadata={"first_name": "Alejandro"}))
    response_a = client_a.post("/api/v1/me/organization")
    app.dependency_overrides.clear()

    client_b = _client_as(db_session, _claims(user_b, email="b@example.com", user_metadata={"first_name": "Beatriz"}))
    response_b = client_b.post("/api/v1/me/organization")
    app.dependency_overrides.clear()

    assert response_a.json()["organization_id"] != response_b.json()["organization_id"]
    assert db_session.query(Organization).count() == 2


def test_provisioning_unblocks_get_current_org_user_afterward(db_session: Session):
    """The actual point of this route: before provisioning, every normal route 403s; after, it works — without touching get_current_org_user itself."""
    user_id = uuid.uuid4()
    claims = _claims(user_id, user_metadata={"first_name": "Ana", "last_name": "Reyes"})
    client = _client_as(db_session, claims)
    try:
        before = client.get("/api/v1/me")
        assert before.status_code == 403

        provision = client.post("/api/v1/me/organization")
        assert provision.status_code == 200

        after = client.get("/api/v1/me")
        assert after.status_code == 200
        assert after.json()["organization_id"] == provision.json()["organization_id"]
    finally:
        app.dependency_overrides.clear()


def test_provision_records_an_audit_log_entry(db_session: Session):
    user_id = uuid.uuid4()
    client = _client_as(db_session, _claims(user_id, user_metadata={"first_name": "Ana"}))
    try:
        response = client.post("/api/v1/me/organization")
        organization_id = uuid.UUID(response.json()["organization_id"])

        entries = db_session.query(AuditLog).filter(AuditLog.organization_id == organization_id).all()
        assert len(entries) == 1
        assert entries[0].action == "ORGANIZATION_CREATED"
        assert entries[0].actor_user_id == user_id
        assert entries[0].entity_type == "organization"
    finally:
        app.dependency_overrides.clear()


def test_provision_missing_bearer_token_is_401(db_session: Session):
    """Uses a bare TestClient (not the `client` fixture, and no get_current_claims override) so the real 401 path runs."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post("/api/v1/me/organization")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
