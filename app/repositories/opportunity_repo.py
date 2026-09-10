from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.opportunity import Opportunity
from app.repositories.base import OrgScopedRepository
from app.schemas.enums import OPPORTUNITY_CLOSED_STAGES


class OpportunityRepository(OrgScopedRepository[Opportunity]):
    model = Opportunity

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        opportunity_type: str | None = None,
        stage: str | None = None,
        owner_user_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        property_id: uuid.UUID | None = None,
        buyer_requirement_id: uuid.UUID | None = None,
        expected_close_from: datetime | None = None,
        expected_close_to: datetime | None = None,
        is_closed: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Opportunity]:
        stmt = select(Opportunity).where(Opportunity.organization_id == organization_id)
        if opportunity_type is not None:
            stmt = stmt.where(Opportunity.opportunity_type == opportunity_type)
        if stage is not None:
            stmt = stmt.where(Opportunity.stage == stage)
        if owner_user_id is not None:
            stmt = stmt.where(Opportunity.owner_user_id == owner_user_id)
        if contact_id is not None:
            stmt = stmt.where(Opportunity.contact_id == contact_id)
        if property_id is not None:
            stmt = stmt.where(Opportunity.property_id == property_id)
        if buyer_requirement_id is not None:
            stmt = stmt.where(Opportunity.buyer_requirement_id == buyer_requirement_id)
        if expected_close_from is not None:
            stmt = stmt.where(Opportunity.expected_close_date >= expected_close_from)
        if expected_close_to is not None:
            stmt = stmt.where(Opportunity.expected_close_date <= expected_close_to)
        if is_closed is True:
            stmt = stmt.where(Opportunity.stage.in_(OPPORTUNITY_CLOSED_STAGES))
        elif is_closed is False:
            stmt = stmt.where(Opportunity.stage.not_in(OPPORTUNITY_CLOSED_STAGES))
        stmt = stmt.order_by(Opportunity.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def list_inactive(self, organization_id: uuid.UUID, *, now: datetime, since: timedelta) -> list[Opportunity]:
        """
        Used by app/automation/detectors.py's detect_inactive_opportunities —
        same explicit-`now`-parameter convention as TaskRepository.list_overdue
        so the boundary is testable with a controlled clock. `updated_at`
        (TimestampMixin, auto-stamped on every write) is the one existing
        signal of "when did anything last happen to this deal" — the same
        column OpportunityService.update already bumps on every stage
        change, note, or field edit, so no new activity-tracking column is
        needed. A closed (won/lost) opportunity is excluded: it isn't
        "going stale," it's finished.
        """
        threshold = now - since
        stmt = select(Opportunity).where(
            Opportunity.organization_id == organization_id,
            Opportunity.updated_at < threshold,
            Opportunity.stage.not_in(OPPORTUNITY_CLOSED_STAGES),
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_contact(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> list[Opportunity]:
        stmt = (
            select(Opportunity)
            .where(Opportunity.organization_id == organization_id, Opportunity.contact_id == contact_id)
            .order_by(Opportunity.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
