from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.property import Property, PropertyFeature
from app.repositories.base import OrgScopedRepository


class PropertyRepository(OrgScopedRepository[Property]):
    model = Property

    def get(self, organization_id: uuid.UUID, id: uuid.UUID) -> Property | None:
        stmt = (
            select(Property)
            .options(selectinload(Property.features))
            .where(Property.id == id, Property.organization_id == organization_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Property]:
        stmt = (
            select(Property)
            .options(selectinload(Property.features))
            .where(Property.organization_id == organization_id)
            .order_by(Property.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_feature(self, property_: Property, feature_key: str) -> PropertyFeature:
        existing = next((f for f in property_.features if f.feature_key == feature_key), None)
        if existing:
            return existing
        feature = PropertyFeature(property_id=property_.id, feature_key=feature_key)
        self.db.add(feature)
        self.db.flush()
        return feature

    def remove_feature(self, property_: Property, feature_key: str) -> None:
        feature = next((f for f in property_.features if f.feature_key == feature_key), None)
        if feature:
            self.db.delete(feature)
            self.db.flush()