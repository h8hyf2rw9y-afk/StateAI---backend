import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.schemas.common import ORMModel
from app.schemas.enums import OrganizationInvitationStatus, UserRole

# Never "owner" — see OrganizationInvitationService.create. A second owner
# isn't a real concept this app's authorization model supports anywhere else.
INVITABLE_ROLES: tuple[str, ...] = ("admin", "agent")


class OrganizationInvitationCreate(BaseModel):
    email: EmailStr
    role: UserRole = "agent"


class OrganizationInvitationRead(ORMModel):
    """
    The list/management shape — deliberately NEVER includes `token`. The
    only response that ever carries the raw token is the one right after
    creation (OrganizationInvitationCreated), so a link can't be
    re-obtained by anyone who can merely list invitations.
    """

    id: uuid.UUID
    email: str
    role: str
    status: OrganizationInvitationStatus
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class OrganizationInvitationCreated(OrganizationInvitationRead):
    """The one-time response that actually carries the shareable link's token."""

    token: str


class OrganizationInvitationPreview(BaseModel):
    """
    Public (unauthenticated) — what the register page shows BEFORE anyone
    signs in, so deliberately as little as possible: never the inviting
    organization's id, never the invited email, never who sent it (names
    live in Supabase Auth, not this table, and this route has no session to
    ask Supabase on the caller's behalf) — just whether the link still
    works and, if so, which organization it joins.
    """

    valid: bool
    organization_name: str | None = None


class OrganizationInvitationAccept(BaseModel):
    token: str
