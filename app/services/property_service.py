from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.property import Property
from app.repositories.property_repo import PropertyRepository
from app.schemas.property import PropertyCreate, PropertyRead, PropertyUpdate
from app.services.audit_service import AuditService


def _check_ownership_consistency(prop: Property) -> None:
    """Re-validates the *merged* row after a partial update — same reasoning as app/services/buyer_requirement_service.py's _check_minmax, needed because PropertyUpdate's own model has no way to see fields the caller didn't include in this particular PATCH."""
    if prop.ownership_type == "own" and prop.collaboration_status is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "collaboration_status only applies to an external (ownership_type='external') property.",
        )


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

        fields = data.model_dump(exclude_unset=True)
        # OrgScopedRepository.update() skips None values (see its own
        # docstring), so switching back to "own" must clear the
        # external/collaboration fields directly on the object — the same
        # "reopening" pattern app/services/opportunity_service.py already
        # uses for closed_at/lost_reason when an opportunity moves out of a
        # closed stage.
        if fields.get("ownership_type") == "own" and prop.ownership_type != "own":
            prop.external_source = None
            prop.external_advisor_name = None
            prop.external_advisor_contact = None
            prop.collaboration_status = None

        updated = self.repo.update(prop, **fields)
        _check_ownership_consistency(updated)
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
