from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.property_interest import PropertyInterest
from app.repositories.base import OrgScopedRepository


class PropertyInterestRepository(OrgScopedRepository[PropertyInterest]):
    model = PropertyInterest

    def list_for_contact(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> list[PropertyInterest]:
        stmt = (
            select(PropertyInterest)
            .where(
                PropertyInterest.organization_id == organization_id,
                PropertyInterest.contact_id == contact_id,
            )
            .order_by(PropertyInterest.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())