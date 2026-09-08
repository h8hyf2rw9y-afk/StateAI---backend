from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.repositories.contact_repo import ContactRepository
from app.schemas.contact import ContactCreate, ContactUpdate


class ContactService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ContactRepository(db)

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Contact]:
        return self.repo.list(organization_id, limit=limit, offset=offset)

    def get_or_404(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> Contact:
        contact = self.repo.get(organization_id, contact_id)
        if contact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        return contact

    def create(self, organization_id: uuid.UUID, data: ContactCreate) -> Contact:
        contact = self.repo.create(organization_id, **data.model_dump())
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def update(self, organization_id: uuid.UUID, contact_id: uuid.UUID, data: ContactUpdate) -> Contact:
        contact = self.get_or_404(organization_id, contact_id)
        updated = self.repo.update(contact, **data.model_dump(exclude_unset=True))
        if not updated.email and not updated.phone:
            self.db.rollback()
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "A contact must keep at least an email or a phone."
            )
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def delete(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> None:
        contact = self.get_or_404(organization_id, contact_id)
        self.repo.delete(contact)
        self.db.commit()

    def add_role(self, organization_id: uuid.UUID, contact_id: uuid.UUID, role_key: str) -> Contact:
        contact = self.get_or_404(organization_id, contact_id)
        self.repo.add_role(contact, role_key)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def remove_role(self, organization_id: uuid.UUID, contact_id: uuid.UUID, role_key: str) -> Contact:
        contact = self.get_or_404(organization_id, contact_id)
        self.repo.remove_role(contact, role_key)
        self.db.commit()
        self.db.refresh(contact)
        return contact