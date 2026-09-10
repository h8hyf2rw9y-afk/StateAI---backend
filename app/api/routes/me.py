import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import build_current_user, get_current_claims, get_current_org_user, get_current_user_id
from app.schemas.user import CurrentUser, OrganizationCreate
from app.services.onboarding_service import OnboardingService

router = APIRouter(tags=["me"])


@router.get("/me", response_model=CurrentUser)
def read_current_user(current_user: CurrentUser = Depends(get_current_org_user)) -> CurrentUser:
    """Whoami — the simplest possible proof the JWT verification + org lookup works end to end."""
    return current_user


def _default_organization_name(claims: dict) -> str:
    """A brand-new signup has no organization yet to name one after — derived from the same JWT claims RegisterForm already populates (first_name/last_name), never inventing anything the user didn't provide."""
    metadata = claims.get("user_metadata") or {}
    first_name = metadata.get("first_name")
    last_name = metadata.get("last_name")
    if first_name or last_name:
        full_name = " ".join(part for part in (first_name, last_name) if part)
        return f"{full_name}'s Organization"
    email = claims.get("email")
    if email:
        return f"{email}'s Organization"
    return "My Organization"


@router.post("/me/organization", response_model=CurrentUser)
def provision_my_organization(
    data: OrganizationCreate = OrganizationCreate(),
    user_id: uuid.UUID = Depends(get_current_user_id),
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """
    Self-service onboarding: turns a real, verified Supabase session with
    no `users` row yet (see get_current_org_user's 403 branch in
    app/core/security.py) into a usable, org-scoped account. Depends on
    get_current_user_id/get_current_claims, not get_current_org_user — the
    latter is exactly the dependency that currently 403s for the caller
    this route exists to help.

    Idempotent: a caller who's already provisioned just gets their existing
    identity back (see OnboardingService.provision) — never a second
    organization, so this is always safe to call, including as a matter of
    course right after every login (see the frontend's LoginForm/
    RegisterForm/auth callback).
    """
    name = data.name or _default_organization_name(claims)
    user = OnboardingService(db).provision(user_id, name)
    return build_current_user(claims, user)
