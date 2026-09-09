from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.repositories.activity_repo import ActivityRepository
from app.repositories.buyer_requirement_repo import BuyerRequirementRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.opportunity_repo import OpportunityRepository
from app.repositories.property_repo import PropertyRepository
from app.schemas.enums import OPPORTUNITY_CLOSED_STAGES, OPPORTUNITY_STAGES_BY_TYPE
from app.schemas.opportunity import OpportunityCreate, OpportunityRead, OpportunityUpdate
from app.services.audit_service import AuditService

_STAGE_LABELS = {
    "qualification": "Qualification", "search": "Search", "listing": "Listing", "marketing": "Marketing",
    "property_selected": "Property selected", "showing": "Showing", "offer": "Offer",
    "negotiation": "Negotiation", "reservation": "Reservation", "contract": "Contract",
    "closing": "Closing", "won": "Won", "lost": "Lost",
}


class OpportunityService:
    """
    The actual sales process — see app/models/opportunity.py. One shared
    OPPORTUNITY_STAGES enum (app/schemas/enums.py) covers both `buy` and
    `sell`, rather than two separate stage systems: the two pipelines are
    identical for most of their length (offer through won/lost) and diverge
    only at the start (search vs. listing/marketing) — duplicating 8 of 13
    values into a second enum would be pure repetition for no benefit.
    OPPORTUNITY_STAGES_BY_TYPE is the (data, not code) boundary that keeps
    a BUY opportunity out of a SELL-only stage and vice versa; see
    _validate_stage. This is intentionally not a workflow/state-transition
    engine — a stage can move to any other stage valid for its type,
    forward or backward, in one PATCH; only the *destination* is checked,
    never the path taken to reach it.

    No hard DELETE exists for this entity — see app/api/routes/opportunities.py
    for why: an Opportunity is business history, so "deleting" one in this
    domain means marking it `lost` (with a `lost_reason`), not removing the
    row. Reopening (moving a closed opportunity back to a working stage) is
    supported: closed_at/lost_reason are cleared automatically.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = OpportunityRepository(db)
        self.contact_repo = ContactRepository(db)
        self.property_repo = PropertyRepository(db)
        self.buyer_requirement_repo = BuyerRequirementRepository(db)
        self.activity_repo = ActivityRepository(db)
        self.audit = AuditService(db)

    # --- reads ---------------------------------------------------------------------

    def list(self, organization_id: uuid.UUID, **filters) -> list[Opportunity]:
        return self.repo.list(organization_id, **filters)

    def list_for_contact(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> list[Opportunity]:
        self._get_contact_or_404(organization_id, contact_id)
        return self.repo.list_for_contact(organization_id, contact_id)

    def get_or_404(self, organization_id: uuid.UUID, opportunity_id: uuid.UUID) -> Opportunity:
        opportunity = self.repo.get(organization_id, opportunity_id)
        if opportunity is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found.")
        return opportunity

    def _get_contact_or_404(self, organization_id: uuid.UUID, contact_id: uuid.UUID):
        contact = self.contact_repo.get(organization_id, contact_id)
        if contact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        return contact

    # --- validation ------------------------------------------------------------------

    @staticmethod
    def _validate_stage(opportunity_type: str, stage: str) -> None:
        valid = OPPORTUNITY_STAGES_BY_TYPE[opportunity_type]
        if stage not in valid:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"'{stage}' is not a valid stage for a {opportunity_type} opportunity. Valid stages: {', '.join(valid)}.",
            )

    @staticmethod
    def _validate_lost_reason(stage: str, lost_reason: str | None) -> None:
        if stage == "lost" and not lost_reason:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "lost_reason is required when marking an opportunity as lost."
            )

    def _validate_references(
        self, organization_id: uuid.UUID, contact_id: uuid.UUID, property_id, buyer_requirement_id
    ) -> None:
        """Never trusts a client-supplied property/buyer_requirement id — each must resolve within this same organization (never trust org from the client — see app/core/security.py), and a buyer_requirement, if given, must actually belong to this opportunity's own contact (property has no owning-contact field in this schema to cross-check against — see the README)."""
        if property_id is not None and self.property_repo.get(organization_id, property_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")
        if buyer_requirement_id is not None:
            requirement = self.buyer_requirement_repo.get(organization_id, buyer_requirement_id)
            if requirement is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Buyer requirement not found.")
            if requirement.contact_id != contact_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "buyer_requirement_id must belong to this opportunity's own contact.",
                )

    # --- writes ------------------------------------------------------------------------

    def create(
        self, organization_id: uuid.UUID, contact_id: uuid.UUID, data: OpportunityCreate, actor_user_id: uuid.UUID | None
    ) -> Opportunity:
        self._get_contact_or_404(organization_id, contact_id)
        self._validate_references(organization_id, contact_id, data.property_id, data.buyer_requirement_id)
        self._validate_stage(data.opportunity_type, data.stage)
        self._validate_lost_reason(data.stage, data.lost_reason)

        fields = data.model_dump()
        # Defaults to the creator if no explicit owner is given — a manager
        # can still assign it to someone else by passing owner_user_id.
        if fields.get("owner_user_id") is None:
            fields["owner_user_id"] = actor_user_id
        if data.stage in OPPORTUNITY_CLOSED_STAGES:
            fields["closed_at"] = datetime.now(timezone.utc)

        opportunity = self.repo.create(
            organization_id, contact_id=contact_id, created_by_user_id=actor_user_id, **fields
        )
        after = OpportunityRead.model_validate(opportunity).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="opportunity",
            entity_id=opportunity.id,
            action="OPPORTUNITY_CREATED",
            after=after,
        )
        self.db.commit()
        self.db.refresh(opportunity)
        return opportunity

    def update(
        self,
        organization_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        data: OpportunityUpdate,
        actor_user_id: uuid.UUID | None,
    ) -> Opportunity:
        opportunity = self.get_or_404(organization_id, opportunity_id)
        before_stage = opportunity.stage
        before = OpportunityRead.model_validate(opportunity).model_dump(mode="json")

        fields = data.model_dump(exclude_unset=True)
        new_property_id = fields.get("property_id", opportunity.property_id)
        new_buyer_requirement_id = fields.get("buyer_requirement_id", opportunity.buyer_requirement_id)
        self._validate_references(organization_id, opportunity.contact_id, new_property_id, new_buyer_requirement_id)

        new_stage = fields.get("stage", before_stage)
        self._validate_stage(opportunity.opportunity_type, new_stage)
        new_lost_reason = fields.get("lost_reason", opportunity.lost_reason)
        self._validate_lost_reason(new_stage, new_lost_reason)

        stage_changed = "stage" in fields and new_stage != before_stage
        if stage_changed:
            if new_stage in OPPORTUNITY_CLOSED_STAGES:
                if "closed_at" not in fields:
                    fields["closed_at"] = datetime.now(timezone.utc)
            elif before_stage in OPPORTUNITY_CLOSED_STAGES:
                # Reopening — OrgScopedRepository.update() skips None values,
                # so these are cleared directly on the object rather than
                # via the fields dict passed to it below.
                opportunity.closed_at = None
                opportunity.lost_reason = None

        updated = self.repo.update(opportunity, **fields)
        after = OpportunityRead.model_validate(updated).model_dump(mode="json")

        if stage_changed:
            self._record_stage_change_activity(organization_id, updated, before_stage, new_stage, actor_user_id)
            if new_stage == "won":
                action = "OPPORTUNITY_WON"
            elif new_stage == "lost":
                action = "OPPORTUNITY_LOST"
            elif before_stage in OPPORTUNITY_CLOSED_STAGES:
                action = "OPPORTUNITY_REOPENED"
            else:
                action = "OPPORTUNITY_STAGE_CHANGED"
        else:
            action = "OPPORTUNITY_UPDATED"

        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="opportunity",
            entity_id=updated.id,
            action=action,
            before=before,
            after=after,
        )
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def _record_stage_change_activity(
        self, organization_id: uuid.UUID, opportunity: Opportunity, before_stage: str, after_stage: str, actor_user_id
    ) -> None:
        """The historical timeline lives in Activities, not duplicated inside Opportunity itself — see the module docstring and the README's Pipeline section."""
        before_label = _STAGE_LABELS.get(before_stage, before_stage)
        after_label = _STAGE_LABELS.get(after_stage, after_stage)
        self.activity_repo.create(
            organization_id,
            contact_id=opportunity.contact_id,
            property_id=opportunity.property_id,
            opportunity_id=opportunity.id,
            created_by_user_id=actor_user_id,
            activity_type="stage_change",
            direction=None,
            occurred_at=datetime.now(timezone.utc),
            notes=f"Opportunity stage changed from {before_label} to {after_label}.",
        )
