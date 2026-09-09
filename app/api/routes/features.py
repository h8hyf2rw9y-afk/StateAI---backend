from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.feature import FeatureRead
from app.schemas.user import CurrentUser
from app.services.feature_service import FeatureService

router = APIRouter(prefix="/features", tags=["features"])


@router.get("", response_model=list[FeatureRead])
def list_features(
    active: bool = Query(True, description="Filters by is_active. Defaults to true (active features only)."),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[FeatureRead]:
    """
    The feature catalog (app/models/feature.py) — the authoritative source for every
    feature_key used by property_features and buyer_requirement_features. Global,
    not org-scoped data (see FeatureRepository), but still requires auth for the
    same consistent security posture as every other endpoint.

    Defaults to active-only. A plain boolean filter, passed straight through to
    the repository — no separate "include_inactive"/"all" flag, per "do not
    over-engineer filtering."
    """
    return FeatureService(db).list(active=active)
