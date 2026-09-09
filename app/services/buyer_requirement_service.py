from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.buyer_requirement import BuyerRequirement
from app.repositories.buyer_requirement_repo import BuyerRequirementRepository
from app.repositories.contact_repo import ContactRepository
from app.schemas.buyer_requirement import (
    BuyerRequirementCreate,
    BuyerRequirementRead,
    BuyerRequirementUpdate,
    FeatureAssign,
    LocationCreate,
    MINMAX_FIELDS,
)
from app.services.audit_service import AuditService


def _check_minmax(requirement: BuyerRequirement) -> None:
    """Re-validates every min<=max pair against the *merged* row after a partial update — see BuyerRequirementUpdate's note on why this can't be checked at the schema layer alone."""
    for field in MINMAX_FIELDS:
        lo, hi = getattr(requirement, f"{field}_min"), getattr(requirement, f"{field}_max")
        if lo is not None and hi is not None and lo > hi:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field}_min must be <= {field}_max."
            )


class BuyerRequirementService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = BuyerRequirementRepository(db)
        self.contact_repo = ContactRepository(db)
        self.audit = AuditService(db)

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[BuyerRequirement]:
        return self.repo.list(organization_id, limit=limit, offset=offset)

    def list_for_contact(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> list[BuyerRequirement]:
        self._get_contact_or_404(organization_id, contact_id)
        return self.repo.list_for_contact(organization_id, contact_id)

    def get_or_404(self, organization_id: uuid.UUID, requirement_id: uuid.UUID) -> BuyerRequirement:
        requirement = self.repo.get(organization_id, requirement_id)
        if requirement is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Buyer requirement not found.")
        return requirement

    def _get_contact_or_404(self, organization_id: uuid.UUID, contact_id: uuid.UUID):
        contact = self.contact_repo.get(organization_id, contact_id)
        if contact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        return contact

    def create(
        self,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        data: BuyerRequirementCreate,
        actor_user_id: uuid.UUID | None = None,
    ) -> BuyerRequirement:
        self._get_contact_or_404(organization_id, contact_id)
        requirement = self.repo.create(organization_id, contact_id=contact_id, **data.model_dump())
        after = BuyerRequirementRead.model_validate(requirement).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="buyer_requirement",
            entity_id=requirement.id,
            action="BUYER_REQUIREMENT_CREATED",
            after=after,
        )
        self.db.commit()
        self.db.refresh(requirement)
        return requirement

    def update(
        self,
        organization_id: uuid.UUID,
        requirement_id: uuid.UUID,
        data: BuyerRequirementUpdate,
        actor_user_id: uuid.UUID | None = None,
    ) -> BuyerRequirement:
        requirement = self.get_or_404(organization_id, requirement_id)
        before = BuyerRequirementRead.model_validate(requirement).model_dump(mode="json")
        updated = self.repo.update(requirement, **data.model_dump(exclude_unset=True))
        _check_minmax(updated)
        after = BuyerRequirementRead.model_validate(updated).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="buyer_requirement",
            entity_id=updated.id,
            action="BUYER_REQUIREMENT_UPDATED",
            before=before,
            after=after,
        )
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def delete(
        self, organization_id: uuid.UUID, requirement_id: uuid.UUID, actor_user_id: uuid.UUID | None = None
    ) -> None:
        requirement = self.get_or_404(organization_id, requirement_id)
        before = BuyerRequirementRead.model_validate(requirement).model_dump(mode="json")
        deleted_id = requirement.id
        self.repo.delete(requirement)
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="buyer_requirement",
            entity_id=deleted_id,
            action="BUYER_REQUIREMENT_DELETED",
            before=before,
        )
        self.db.commit()

    def add_location(
        self, organization_id: uuid.UUID, requirement_id: uuid.UUID, data: LocationCreate
    ) -> BuyerRequirement:
        requirement = self.get_or_404(organization_id, requirement_id)
        self.repo.add_location(requirement, **data.model_dump())
        self.db.commit()
        self.db.refresh(requirement)
        return requirement

    def add_feature(
        self, organization_id: uuid.UUID, requirement_id: uuid.UUID, data: FeatureAssign
    ) -> BuyerRequirement:
        requirement = self.get_or_404(organization_id, requirement_id)
        self.repo.add_feature(requirement, data.feature_key, data.classification)
        self.db.commit()
        self.db.refresh(requirement)
        return requirement

    def remove_location(
        self, organization_id: uuid.UUID, requirement_id: uuid.UUID, location_id: uuid.UUID
    ) -> BuyerRequirement:
        """get_or_404 is the tenant-isolation boundary: a requirement_id from another
        organization 404s here before we ever touch its locations, and location_id is
        only ever matched within *this* (already org-verified) requirement's own
        collection — see BuyerRequirementRepository.remove_location."""
        requirement = self.get_or_404(organization_id, requirement_id)
        self.repo.remove_location(requirement, location_id)
        self.db.commit()
        self.db.refresh(requirement)
        return requirement

    def remove_feature(
        self, organization_id: uuid.UUID, requirement_id: uuid.UUID, feature_key: str
    ) -> BuyerRequirement:
        """Removes only the buyer_requirement_features relationship row, not the global Feature catalog row."""
        requirement = self.get_or_404(organization_id, requirement_id)
        self.repo.remove_feature(requirement, feature_key)
        self.db.commit()
        self.db.refresh(requirement)
        return requirement