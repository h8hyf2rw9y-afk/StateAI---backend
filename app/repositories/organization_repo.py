from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.organization import Organization, User


class OrganizationRepository:
    """
    Deliberately NOT an OrgScopedRepository, same reasoning as
    FeatureRepository (app/repositories/feature_repo.py): Organization has
    no organization_id to scope by — it IS the tenant boundary everything
    else scopes against. Create-only: there's no organization list/get-by-id
    endpoint yet (no org-management UI exists), so nothing else is needed
    here today — see app/services/onboarding_service.py, the only caller.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, name: str) -> Organization:
        organization = Organization(name=name)
        self.db.add(organization)
        self.db.flush()
        return organization


class UserRepository:
    """
    The `users` bridge row between Supabase Auth and this schema (see
    app/models/organization.py's own docstring). `get` mirrors the exact
    lookup app/core/security.py's get_current_org_user already does via
    db.get(User, user_id) — kept here too so the read and write sides of
    this one row live next to each other. Deliberately NOT an
    OrgScopedRepository: a user's own id (not organization_id) is the
    natural key here, and there's no "list every user in my org" endpoint
    yet to justify that base class.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def create(self, user_id: uuid.UUID, organization_id: uuid.UUID, role: str) -> User:
        user = User(id=user_id, organization_id=organization_id, role=role)
        self.db.add(user)
        self.db.flush()
        return user
