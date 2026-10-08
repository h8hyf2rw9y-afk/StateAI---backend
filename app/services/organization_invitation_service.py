from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.organization import Organization, User
from app.models.organization_invitation import OrganizationInvitation
from app.repositories.organization_invitation_repo import OrganizationInvitationRepository
from app.repositories.organization_repo import UserRepository
from app.schemas.organization_invitation import (
    INVITABLE_ROLES,
    OrganizationInvitationAccept,
    OrganizationInvitationCreate,
    OrganizationInvitationCreated,
    OrganizationInvitationPreview,
    OrganizationInvitationRead,
)
from app.schemas.user import CurrentUser
from app.services.audit_service import AuditService

_ENTITY_TYPE = "organization_invitation"
_INVITATION_LIFETIME = timedelta(days=7)
_INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_invitation_code() -> str:
    """A human-friendly ~50-bit one-time code, excluding ambiguous 0/O/1/I characters."""
    compact = "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(10))
    return f"{compact[:5]}-{compact[5:]}"


def _normalize_invitation_credential(value: str) -> str:
    """Accept codes typed with lowercase, spaces or omitted hyphen; preserve legacy long URL tokens exactly."""
    raw = value.strip()
    compact = raw.replace("-", "").replace(" ", "").upper()
    if len(compact) == 10 and all(character in _INVITE_CODE_ALPHABET for character in compact):
        return f"{compact[:5]}-{compact[5:]}"
    return raw


def _is_expired(expires_at: datetime) -> bool:
    """Postgres (DateTime(timezone=True)) always hands back a tz-aware value; SQLite — only used in tests — silently strips it. Treat a naive value as the UTC it was written as, so this works the same against both."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)


class OrganizationInvitationService:
    """
    Brings a specific person into an EXISTING organization — the self-
    service "create my own" path (OnboardingService) is for everyone else.
    Route-level `require_role("owner", "admin")` gates every write here
    except `accept` (anyone with a verified, unprovisioned session can
    accept — that's the whole point) and `preview` (public, token-only).
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = OrganizationInvitationRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    def create(self, current_user: CurrentUser, data: OrganizationInvitationCreate) -> OrganizationInvitationCreated:
        if data.role not in INVITABLE_ROLES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invitations can only grant the admin, agent or renova_agent role.")
        if current_user.role != "owner" and data.role != "renova_agent":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only the owner can invite administrators or general CRM agents.",
            )

        token = _new_invitation_code()
        expires_at = datetime.now(timezone.utc) + _INVITATION_LIFETIME
        invitation = self.repo.create(
            current_user.organization_id,
            invited_by_user_id=current_user.id,
            email=data.email.strip().lower(),
            role=data.role,
            token=token,
            expires_at=expires_at,
        )
        self.db.flush()
        self.db.refresh(invitation)
        self.audit.record(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            entity_type=_ENTITY_TYPE,
            entity_id=invitation.id,
            action="ORGANIZATION_INVITATION_CREATED",
            after={"email": invitation.email, "role": invitation.role},
        )
        self.db.commit()
        self.db.refresh(invitation)
        return OrganizationInvitationCreated.model_validate(invitation)

    def list(self, current_user: CurrentUser) -> list[OrganizationInvitationRead]:
        invitations = self.repo.list_for_organization(current_user.organization_id)
        if current_user.role != "owner":
            invitations = [invitation for invitation in invitations if invitation.role == "renova_agent"]
        return [OrganizationInvitationRead.model_validate(i) for i in invitations]

    def revoke(self, current_user: CurrentUser, invitation_id: uuid.UUID) -> None:
        invitation = self.repo.get_for_organization(current_user.organization_id, invitation_id)
        if invitation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
        if current_user.role != "owner" and invitation.role != "renova_agent":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can revoke this invitation.")
        if invitation.status != "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a pending invitation can be revoked.")

        invitation.status = "revoked"
        self.db.flush()
        self.audit.record(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            entity_type=_ENTITY_TYPE,
            entity_id=invitation.id,
            action="ORGANIZATION_INVITATION_REVOKED",
        )
        self.db.commit()

    def preview(self, token: str) -> OrganizationInvitationPreview:
        invitation = self._valid_pending_invitation(_normalize_invitation_credential(token))
        if invitation is None:
            return OrganizationInvitationPreview(valid=False)
        organization = self.db.get(Organization, invitation.organization_id)
        return OrganizationInvitationPreview(valid=True, organization_name=organization.name if organization else None)

    def accept(self, user_id: uuid.UUID, claims: dict, data: OrganizationInvitationAccept) -> User:
        invitation = self.repo.get_by_token(_normalize_invitation_credential(data.token))

        existing = self.user_repo.get(user_id)
        if existing is not None:
            if invitation is not None and existing.organization_id == invitation.organization_id:
                return existing  # Already accepted this same invitation — a safe re-click, not an error.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This account already belongs to a different organization.",
            )

        if invitation is None or invitation.status != "pending" or _is_expired(invitation.expires_at):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This invitation is invalid or has expired.")

        email = (claims.get("email") or "").strip().lower()
        if not email or email != invitation.email:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This invitation was sent to a different email address.",
            )

        user = self.user_repo.create(
            user_id=user_id, organization_id=invitation.organization_id, role=invitation.role, email=email
        )
        invitation.status = "accepted"
        invitation.accepted_by_user_id = user_id
        invitation.accepted_at = datetime.now(timezone.utc)
        self.db.flush()
        self.audit.record(
            organization_id=invitation.organization_id,
            actor_user_id=user_id,
            entity_type=_ENTITY_TYPE,
            entity_id=invitation.id,
            action="ORGANIZATION_INVITATION_ACCEPTED",
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def _valid_pending_invitation(self, token: str) -> OrganizationInvitation | None:
        invitation = self.repo.get_by_token(token)
        if invitation is None or invitation.status != "pending" or _is_expired(invitation.expires_at):
            return None
        return invitation
