from __future__ import annotations

import uuid

from sqlalchemy import exists, not_, select
from sqlalchemy.orm import selectinload

from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact, ContactRole
from app.repositories.base import OrgScopedRepository


class ContactRepository(OrgScopedRepository[Contact]):
    model = Contact

    def get(self, organization_id: uuid.UUID, id: uuid.UUID) -> Contact | None:
        stmt = (
            select(Contact)
            .options(selectinload(Contact.roles))
            .where(Contact.id == id, Contact.organization_id == organization_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Contact]:
        stmt = (
            select(Contact)
            .options(selectinload(Contact.roles))
            .where(Contact.organization_id == organization_id)
            .order_by(Contact.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_without_buyer_requirements(self, organization_id: uuid.UUID) -> list[Contact]:
        """
        Used by app/automation/detectors.py's detect_contacts_missing_requirements.
        A single NOT EXISTS query, same "one purpose-built query, not an
        N+1 loop over list()" reasoning as TaskRepository.list_overdue —
        a contact "has no buyer requirements" if zero rows reference it at
        all, regardless of any requirement's status (even a cancelled one
        proves someone already started the qualification conversation).
        """
        stmt = select(Contact).where(
            Contact.organization_id == organization_id,
            not_(exists().where(BuyerRequirement.contact_id == Contact.id)),
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_role(self, contact: Contact, role_key: str) -> ContactRole:
        existing = next((r for r in contact.roles if r.role_key == role_key), None)
        if existing:
            return existing
        role = ContactRole(contact_id=contact.id, role_key=role_key)
        self.db.add(role)
        self.db.flush()
        return role

    def remove_role(self, contact: Contact, role_key: str) -> None:
        role = next((r for r in contact.roles if r.role_key == role_key), None)
        if role:
            self.db.delete(role)
            self.db.flush()