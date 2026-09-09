from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.feature import Feature
from app.repositories.feature_repo import FeatureRepository


class FeatureService:
    def __init__(self, db: Session) -> None:
        self.repo = FeatureRepository(db)

    def list(self, *, active: bool | None = True) -> list[Feature]:
        """`active=None` returns the full catalog (active and inactive) — kept available
        for internal/future callers even though the API layer (app/api/routes/features.py)
        always passes a concrete bool today."""
        return self.repo.list(active=active)
