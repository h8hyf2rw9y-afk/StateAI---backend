from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.property_interest import PropertyInterest
from app.repositories.contact_repo import ContactRepository
from app.repositories.property_interest_repo import PropertyInterestRepository
from app.repositories.property_repo import PropertyRepository
from app.schemas.property_interest import PropertyInterestCreate, PropertyInterestUpdate


class PropertyInterestService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PropertyInterestRepository(db)
        self.contact_repo = ContactRepository(db)
        self.property_repo = PropertyRepository(db)

    def list_for_contact(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> list[PropertyInterest]:
        self._get_contact_or_404(organization_id, contact_id)
        return self.repo.list_for_contact(organization_id, contact_id)

    def get_or_404(self, organization_id: uuid.UUID, interest_id: uuid.UUID) -> PropertyInterest:
        interest = self.repo.get(organization_id, interest_id)
        if interest is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property interest not found.")
        return interest

    def _get_contact_or_404(self, organization_id: uuid.UUID, contact_id: uuid.UUID):
        contact = self.contact_repo.get(organization_id, contact_id)
        if contact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        return contact

    def create(
        self, organization_id: uuid.UUID, contact_id: uuid.UUID, data: PropertyInterestCreate
    ) -> PropertyInterest:
        self._get_contact_or_404(organization_id, contact_id)
        if self.property_repo.get(organization_id, data.property_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")
        interest = self.repo.create(organization_id, contact_id=contact_id, **data.model_dump())
        self.db.commit()
        self.db.refresh(interest)
        return interest

    def update(
        self, organization_id: uuid.UUID, interest_id: uuid.UUID, data: PropertyInterestUpdate
    ) -> PropertyInterest:
        interest = self.get_or_404(organization_id, interest_id)
        updated = self.repo.update(interest, **data.model_dump(exclude_unset=True))
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def delete(self, organization_id: uuid.UUID, interest_id: uuid.UUID) -> None:
        interest = self.get_or_404(organization_id, interest_id)
        self.repo.delete(interest)
        self.db.commit()