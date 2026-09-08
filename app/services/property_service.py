from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.property import Property
from app.repositories.property_repo import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyUpdate


class PropertyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PropertyRepository(db)

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Property]:
        return self.repo.list(organization_id, limit=limit, offset=offset)

    def get_or_404(self, organization_id: uuid.UUID, property_id: uuid.UUID) -> Property:
        prop = self.repo.get(organization_id, property_id)
        if prop is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")
        return prop

    def create(self, organization_id: uuid.UUID, data: PropertyCreate) -> Property:
        prop = self.repo.create(organization_id, **data.model_dump())
        self.db.commit()
        self.db.refresh(prop)
        return prop

    def update(self, organization_id: uuid.UUID, property_id: uuid.UUID, data: PropertyUpdate) -> Property:
        prop = self.get_or_404(organization_id, property_id)
        updated = self.repo.update(prop, **data.model_dump(exclude_unset=True))
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def delete(self, organization_id: uuid.UUID, property_id: uuid.UUID) -> None:
        prop = self.get_or_404(organization_id, property_id)
        self.repo.delete(prop)
        self.db.commit()

    def add_feature(self, organization_id: uuid.UUID, property_id: uuid.UUID, feature_key: str) -> Property:
        prop = self.get_or_404(organization_id, property_id)
        self.repo.add_feature(prop, feature_key)
        self.db.commit()
        self.db.refresh(prop)
        return prop

    def remove_feature(self, organization_id: uuid.UUID, property_id: uuid.UUID, feature_key: str) -> Property:
        prop = self.get_or_404(organization_id, property_id)
        self.repo.remove_feature(prop, feature_key)
        self.db.commit()
        self.db.refresh(prop)
        return prop