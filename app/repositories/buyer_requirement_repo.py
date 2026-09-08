from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.buyer_requirement import (
    BuyerRequirement,
    BuyerRequirementFeature,
    BuyerRequirementLocation,
)
from app.repositories.base import OrgScopedRepository

_EAGER = (selectinload(BuyerRequirement.locations), selectinload(BuyerRequirement.features))


class BuyerRequirementRepository(OrgScopedRepository[BuyerRequirement]):
    model = BuyerRequirement

    def get(self, organization_id: uuid.UUID, id: uuid.UUID) -> BuyerRequirement | None:
        stmt = (
            select(BuyerRequirement)
            .options(*_EAGER)
            .where(BuyerRequirement.id == id, BuyerRequirement.organization_id == organization_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[BuyerRequirement]:
        stmt = (
            select(BuyerRequirement)
            .options(*_EAGER)
            .where(BuyerRequirement.organization_id == organization_id)
            .order_by(BuyerRequirement.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_contact(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> list[BuyerRequirement]:
        stmt = (
            select(BuyerRequirement)
            .options(*_EAGER)
            .where(
                BuyerRequirement.organization_id == organization_id,
                BuyerRequirement.contact_id == contact_id,
            )
            .order_by(BuyerRequirement.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_location(self, requirement: BuyerRequirement, **fields) -> BuyerRequirementLocation:
        location = BuyerRequirementLocation(buyer_requirement_id=requirement.id, **fields)
        self.db.add(location)
        self.db.flush()
        return location

    def add_feature(self, requirement: BuyerRequirement, feature_key: str, classification: str) -> BuyerRequirementFeature:
        existing = next((f for f in requirement.features if f.feature_key == feature_key), None)
        if existing:
            existing.classification = classification
            self.db.flush()
            return existing
        feature = BuyerRequirementFeature(
            buyer_requirement_id=requirement.id, feature_key=feature_key, classification=classification
        )
        self.db.add(feature)
        self.db.flush()
        return feature