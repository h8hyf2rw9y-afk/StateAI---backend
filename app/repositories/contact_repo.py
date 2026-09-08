from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

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