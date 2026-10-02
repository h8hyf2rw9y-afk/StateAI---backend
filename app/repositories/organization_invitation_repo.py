from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization_invitation import OrganizationInvitation


class OrganizationInvitationRepository:
    """`get_by_token` is the one lookup that is deliberately NOT organization-scoped — a brand-new, not-yet-provisioned caller has no organization_id to scope by yet; the token itself is the only thing they can prove they have."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        organization_id: uuid.UUID,
        *,
        invited_by_user_id: uuid.UUID,
        email: str,
        role: str,
        token: str,
        expires_at,
    ) -> OrganizationInvitation:
        invitation = OrganizationInvitation(
            organization_id=organization_id,
            invited_by_user_id=invited_by_user_id,
            email=email,
            role=role,
            token=token,
            expires_at=expires_at,
        )
        self.db.add(invitation)
        self.db.flush()
        return invitation

    def get_by_token(self, token: str) -> OrganizationInvitation | None:
        stmt = select(OrganizationInvitation).where(OrganizationInvitation.token == token)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_for_organization(self, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> OrganizationInvitation | None:
        stmt = select(OrganizationInvitation).where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.organization_id == organization_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_organization(self, organization_id: uuid.UUID) -> list[OrganizationInvitation]:
        stmt = (
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == organization_id)
            .order_by(OrganizationInvitation.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
