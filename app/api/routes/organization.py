import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user, require_role
from app.repositories.organization_repo import OrganizationRepository
from app.schemas.organization_invitation import (
    OrganizationInvitationCreate,
    OrganizationInvitationCreated,
    OrganizationInvitationPreview,
    OrganizationInvitationRead,
)
from app.schemas.organization_member import OrganizationMemberRead, OrganizationMemberUpdate
from app.schemas.retify_dashboard import RetifyDashboardPeriod, RetifyDashboardResponse
from app.schemas.user import CurrentUser, OrganizationRead
from app.services.organization_invitation_service import OrganizationInvitationService
from app.services.organization_member_service import OrganizationMemberService
from app.services.retify_dashboard_service import RetifyDashboardService

router = APIRouter(prefix="/organization", tags=["organization"])


@router.get("", response_model=OrganizationRead)
def read_my_organization(
    current_user: CurrentUser = Depends(get_current_org_user), db: Session = Depends(get_db)
) -> OrganizationRead:
    """Just the id/name — any org member can see it (Settings' Organization tab), not just owner/admin."""
    organization = OrganizationRepository(db).get(current_user.organization_id)
    return OrganizationRead.model_validate(organization)


# Bringing a specific person into this SAME organization (as opposed to
# /me/organization, which always creates a brand-new one). Only the owner can
# create, list or revoke invitations. `preview` is the one deliberately public
# exception — the person clicking a /register?invite= link has no session yet.
@router.post(
    "/invitations", response_model=OrganizationInvitationCreated, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("owner"))],
)
def create_invitation(
    data: OrganizationInvitationCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> OrganizationInvitationCreated:
    return OrganizationInvitationService(db).create(current_user, data)


@router.get(
    "/invitations", response_model=list[OrganizationInvitationRead],
    dependencies=[Depends(require_role("owner"))],
)
def list_invitations(
    current_user: CurrentUser = Depends(get_current_org_user), db: Session = Depends(get_db)
) -> list[OrganizationInvitationRead]:
    return OrganizationInvitationService(db).list(current_user)


@router.delete(
    "/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role("owner"))],
)
def revoke_invitation(
    invitation_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> None:
    OrganizationInvitationService(db).revoke(current_user, invitation_id)


@router.get("/invitations/preview/{token}", response_model=OrganizationInvitationPreview)
def preview_invitation(token: str, db: Session = Depends(get_db)) -> OrganizationInvitationPreview:
    """Public — no session required. The register page calls this to show which organization a link joins before anyone signs in."""
    return OrganizationInvitationService(db).preview(token)


# The admin "Usuarios" tab lets owner/admin inspect the team. Only the owner
# may change a member's role or active state.
@router.get(
    "/members", response_model=list[OrganizationMemberRead],
    dependencies=[Depends(require_role("owner", "admin"))],
)
def list_members(
    current_user: CurrentUser = Depends(get_current_org_user), db: Session = Depends(get_db)
) -> list[OrganizationMemberRead]:
    return OrganizationMemberService(db).list(current_user)


@router.get(
    "/retify-dashboard",
    response_model=RetifyDashboardResponse,
    dependencies=[Depends(require_role("owner", "admin"))],
)
def read_retify_dashboard(
    period: RetifyDashboardPeriod = Query("30d"),
    assigned_user_id: uuid.UUID | None = Query(None),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> RetifyDashboardResponse:
    return RetifyDashboardService(db).read(
        current_user.organization_id,
        period=period,
        assigned_user_id=assigned_user_id,
    )


@router.patch(
    "/members/{member_id}", response_model=OrganizationMemberRead,
    dependencies=[Depends(require_role("owner"))],
)
def update_member(
    member_id: uuid.UUID,
    data: OrganizationMemberUpdate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> OrganizationMemberRead:
    return OrganizationMemberService(db).update(current_user, member_id, data)
