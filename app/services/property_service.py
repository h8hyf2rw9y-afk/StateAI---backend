from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.property import Property
from app.repositories.property_repo import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyRead, PropertyUpdate
from app.services.audit_service import AuditService


class PropertyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PropertyRepository(db)
        self.audit = AuditService(db)

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Property]:
        return self.repo.list(organization_id, limit=limit, offset=offset)

    def get_or_404(self, organization_id: uuid.UUID, property_id: uuid.UUID) -> Property:
        prop = self.repo.get(organization_id, property_id)
        if prop is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")
        return prop

    def create(
        self, organization_id: uuid.UUID, data: PropertyCreate, actor_user_id: uuid.UUID | None = None
    ) -> Property:
        prop = self.repo.create(organization_id, **data.model_dump())
        after = PropertyRead.model_validate(prop).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="property",
            entity_id=prop.id,
            action="PROPERTY_CREATED",
            after=after,
        )
        self.db.commit()
        self.db.refresh(prop)
        return prop

    def update(
        self,
        organization_id: uuid.UUID,
        property_id: uuid.UUID,
        data: PropertyUpdate,
        actor_user_id: uuid.UUID | None = None,
    ) -> Property:
        prop = self.get_or_404(organization_id, property_id)
        before = PropertyRead.model_validate(prop).model_dump(mode="json")
        updated = self.repo.update(prop, **data.model_dump(exclude_unset=True))
        after = PropertyRead.model_validate(updated).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="property",
            entity_id=updated.id,
            action="PROPERTY_UPDATED",
            before=before,
            after=after,
        )
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def delete(
        self, organization_id: uuid.UUID, property_id: uuid.UUID, actor_user_id: uuid.UUID | None = None
    ) -> None:
        prop = self.get_or_404(organization_id, property_id)
        before = PropertyRead.model_validate(prop).model_dump(mode="json")
        deleted_id = prop.id
        self.repo.delete(prop)
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="property",
            entity_id=deleted_id,
            action="PROPERTY_DELETED",
            before=before,
        )
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
