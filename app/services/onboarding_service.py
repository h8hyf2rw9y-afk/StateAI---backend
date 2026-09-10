from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.organization import User
from app.repositories.organization_repo import OrganizationRepository, UserRepository
from app.services.audit_service import AuditService


class OnboardingService:
    """
    Turns a real, verified-but-unprovisioned Supabase session into a usable
    CRM account: a brand-new Organization plus the `users` bridge row that
    app/core/security.get_current_org_user needs to resolve organization
    scope for every other route. See that function's own 403 branch
    ("This account is not yet assigned to an organization.") — this is the
    self-service fix for exactly that state, replacing what used to be a
    manual `INSERT` (see the backend README's former "What's next" entry).

    Idempotent by design: called from every place a session can newly
    become active (the frontend's LoginForm, RegisterForm, and the OAuth/
    email-confirmation callback), so a repeat call — a double-click, a
    re-triggered effect, a user who simply logs in again later — must never
    create a second organization. It just returns the existing row.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.org_repo = OrganizationRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    def provision(self, user_id: uuid.UUID, name: str) -> User:
        existing = self.user_repo.get(user_id)
        if existing is not None:
            return existing

        organization = self.org_repo.create(name)
        # The first person into a brand-new organization owns it — the same
        # role a human operator has always assigned by hand via the manual
        # INSERT this replaces.
        user = self.user_repo.create(user_id=user_id, organization_id=organization.id, role="owner")
        self.audit.record(
            organization_id=organization.id,
            actor_user_id=user_id,
            entity_type="organization",
            entity_id=organization.id,
            action="ORGANIZATION_CREATED",
            after={"name": organization.name},
        )
        self.db.commit()
        self.db.refresh(user)
        return user
