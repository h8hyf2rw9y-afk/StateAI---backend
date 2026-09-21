from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, exists, not_, or_, select
from sqlalchemy.orm import selectinload

from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact, ContactRole
from app.models.opportunity import Opportunity
from app.repositories.base import OrgScopedRepository
from app.schemas.enums import OPPORTUNITY_CLOSED_STAGES

# A Buyer Requirement no longer counts as "live" once it is cancelled or
# fulfilled (app/schemas/enums.py's BUYER_REQUIREMENT_STATUSES: active,
# paused, fulfilled, cancelled). "paused" is deliberately still live — the
# client hasn't stopped being a client, they've put the search on hold.
_BUYER_REQUIREMENT_ENDED_STATUSES = ("cancelled", "fulfilled")


def active_contact_condition() -> ColumnElement[bool]:
    """
    What "active client" means — the single definition every caller shares
    (GET /contacts?active=...). Nothing is stored on Contact for this: it is
    derived from the relations that already exist, as two correlated EXISTS
    subqueries evaluated inside the same SELECT (one round trip, no N+1, no
    rows pulled into Python to be counted).

    A contact is active when it has AT LEAST ONE of:
      * an Opportunity whose stage is not won/lost (OPPORTUNITY_CLOSED_STAGES), or
      * a Buyer Requirement whose status is not cancelled/fulfilled.

    Not a criterion (on purpose): owning an active Property. The data model
    has no Property -> Contact owner link at all (Property carries only
    ownership_type own/external, i.e. the ADVISOR's inventory vs another
    advisor's), so there is no real relation to derive it from. A seller's
    property still makes them active the moment it is attached to an open
    "sell" Opportunity, which the first rule already covers.

    A contact whose only Opportunities are won/lost and whose Buyer
    Requirements are all cancelled/fulfilled (or that has none) is NOT
    active — history alone never makes a client active.
    """
    open_opportunity = exists().where(
        Opportunity.contact_id == Contact.id,
        Opportunity.organization_id == Contact.organization_id,
        Opportunity.stage.notin_(sorted(OPPORTUNITY_CLOSED_STAGES)),
    )
    live_requirement = exists().where(
        BuyerRequirement.contact_id == Contact.id,
        BuyerRequirement.organization_id == Contact.organization_id,
        BuyerRequirement.status.notin_(_BUYER_REQUIREMENT_ENDED_STATUSES),
    )
    return or_(open_opportunity, live_requirement)


class ContactRepository(OrgScopedRepository[Contact]):
    model = Contact

    def get(self, organization_id: uuid.UUID, id: uuid.UUID) -> Contact | None:
        stmt = (
            select(Contact)
            .options(selectinload(Contact.roles))
            .where(Contact.id == id, Contact.organization_id == organization_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0, active: bool | None = None
    ) -> list[Contact]:
        """`active`: None = every contact (the original behavior), True = only active clients, False = only the rest — see active_contact_condition."""
        stmt = select(Contact).options(selectinload(Contact.roles)).where(Contact.organization_id == organization_id)
        if active is True:
            stmt = stmt.where(active_contact_condition())
        elif active is False:
            stmt = stmt.where(not_(active_contact_condition()))
        stmt = stmt.order_by(Contact.created_at.desc()).limit(limit).offset(offset)
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