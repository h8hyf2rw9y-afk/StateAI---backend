from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
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

    def provision(self, user_id: uuid.UUID, name: str, email: str | None = None) -> User:
        existing = self.user_repo.get(user_id)
        if existing is not None:
            return existing
        if not settings.allow_self_service_signup:
            # Invitation-only mode: never mint a new organization for an
            # uninvited sign-in — they join one through an invitation link.
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Sign-ups are invitation-only. Ask your administrator for an invitation.",
            )

        organization = self.org_repo.create(name)
        # The first person into a brand-new organization owns it — the same
        # role a human operator has always assigned by hand via the manual
        # INSERT this replaces.
        user = self.user_repo.create(user_id=user_id, organization_id=organization.id, role="owner", email=email)
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
