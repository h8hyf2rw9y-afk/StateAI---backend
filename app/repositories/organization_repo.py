from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization, User


class OrganizationRepository:
    """
    Deliberately NOT an OrgScopedRepository, same reasoning as
    FeatureRepository (app/repositories/feature_repo.py): Organization has
    no organization_id to scope by — it IS the tenant boundary everything
    else scopes against. See app/services/onboarding_service.py for create.

    `list_all` was added for app/automation/scheduler.py: the time-based
    detectors (overdue tasks, upcoming appointments) run per-organization
    (every detector call takes one organization_id and never reaches across
    tenants — see app/automation/detectors.py), so the scheduler needs the
    full list of organizations to iterate, the same way it would if this
    were N separate per-tenant cron jobs instead of one process. Still no
    organization list/get-by-id *API route* — this is only ever called from
    that in-process scheduler, never exposed to a client.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, name: str) -> Organization:
        organization = Organization(name=name)
        self.db.add(organization)
        self.db.flush()
        return organization

    def list_all(self) -> list[Organization]:
        return list(self.db.execute(select(Organization)).scalars().all())


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
