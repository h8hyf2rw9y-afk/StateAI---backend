from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.feature import Feature


class FeatureRepository:
    """
    Deliberately NOT an OrgScopedRepository: Feature is a global catalog shared by
    every organization (like Role — app/models/contact.py), not tenant data, so
    there's no organization_id to scope by. See app/api/routes/features.py.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, *, active: bool | None = True) -> list[Feature]:
        stmt = select(Feature).order_by(Feature.label)
        if active is not None:
            stmt = stmt.where(Feature.is_active == active)
        return list(self.db.execute(stmt).scalars().all())
