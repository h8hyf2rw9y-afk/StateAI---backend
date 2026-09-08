from fastapi import APIRouter, Depends

from app.core.security import get_current_org_user
from app.schemas.user import CurrentUser

router = APIRouter(tags=["me"])


@router.get("/me", response_model=CurrentUser)
def read_current_user(current_user: CurrentUser = Depends(get_current_org_user)) -> CurrentUser:
    """Whoami — the simplest possible proof the JWT verification + org lookup works end to end."""
    return current_user
