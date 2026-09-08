from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact
from app.models.property_interest import PropertyInterest
from app.repositories.activity_repo import ActivityRepository
from app.repositories.buyer_requirement_repo import BuyerRequirementRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.property_interest_repo import PropertyInterestRepository
from app.repositories.property_repo import PropertyRepository
from app.schemas.lead_context import (
    ActivityContext,
    BuyerRequirementContext,
    ContactContext,
    EngagementSummary,
    LeadContext,
    PropertyContext,
    PropertyInterestContext,
    TimelineEvent,
)

# Property interest statuses that count as "still open" for engagement_summary —
# lost/won/not_interested are resolved outcomes, not ongoing engagement.
_ACTIVE_PROPERTY_INTEREST_STATUSES = {
    "new", "contacted", "interested", "viewing_scheduled", "viewed", "offer", "negotiation",
}


def _buyer_requirement_summary(br: BuyerRequirement) -> str:
    kind = br.property_type or "property"
    return f"Buyer requirement created ({kind}, status={br.status})"


def _property_interest_summary(pi: PropertyInterest, property_title: str) -> str:
    return f"Interested in {property_title} (status={pi.status})"


class LeadContextService:
    """
    Assembles the structured "everything relevant about this lead" object —
    see app/schemas/lead_context.py for why it's a typed tree, not text.
    This is the Backend Service layer in the required
    AI Agent -> AI Tool -> Backend Service -> Repository -> Supabase flow;
    app/ai/lead_context_tool.py is the thin AI Tool wrapper around it.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.contact_repo = ContactRepository(db)
        self.buyer_requirement_repo = BuyerRequirementRepository(db)
        self.property_interest_repo = PropertyInterestRepository(db)
        self.activity_repo = ActivityRepository(db)
        self.property_repo = PropertyRepository(db)

    def build(self, organization_id: uuid.UUID, contact_id: uuid.UUID, *, activity_limit: int = 20) -> LeadContext:
        contact = self._get_contact_or_404(organization_id, contact_id)

        buyer_requirements = self.buyer_requirement_repo.list_for_contact(organization_id, contact_id)
        property_interests = self.property_interest_repo.list_for_contact(organization_id, contact_id)
        # Ascending (oldest first) — see ActivityRepository.list_for_contact.
        activities_asc = self.activity_repo.list_for_contact(organization_id, contact_id)

        properties_by_id = self._load_referenced_properties(organization_id, property_interests, activities_asc)

        recent_activities = list(reversed(activities_asc))[:activity_limit] if activity_limit > 0 else []

        return LeadContext(
            contact=self._contact_context(contact),
            buyer_requirements=[BuyerRequirementContext.model_validate(br) for br in buyer_requirements],
            property_interests=[PropertyInterestContext.model_validate(pi) for pi in property_interests],
            properties=[PropertyContext.model_validate(p) for p in properties_by_id.values()],
            activities=[ActivityContext.model_validate(a) for a in recent_activities],
            timeline=self._build_timeline(buyer_requirements, property_interests, activities_asc, properties_by_id),
            engagement_summary=self._engagement_summary(buyer_requirements, property_interests, activities_asc),
            generated_at=datetime.now(timezone.utc),
        )

    def _get_contact_or_404(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> Contact:
        contact = self.contact_repo.get(organization_id, contact_id)
        if contact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        return contact

    @staticmethod
    def _contact_context(contact: Contact) -> ContactContext:
        # `roles` is list[str] on the schema but list[ContactRole] on the ORM
        # object — from_attributes can't bridge that gap on its own, unlike
        # every other nested field here (those are proper submodels).
        return ContactContext(
            id=contact.id,
            first_name=contact.first_name,
            last_name=contact.last_name,
            email=contact.email,
            phone=contact.phone,
            preferred_contact_method=contact.preferred_contact_method,
            source=contact.source,
            notes=contact.notes,
            roles=[r.role_key for r in contact.roles],
            created_at=contact.created_at,
        )

    def _load_referenced_properties(self, organization_id, property_interests, activities) -> dict[uuid.UUID, object]:
        property_ids = {pi.property_id for pi in property_interests}
        property_ids |= {a.property_id for a in activities if a.property_id is not None}

        properties: dict[uuid.UUID, object] = {}
        for property_id in property_ids:
            prop = self.property_repo.get(organization_id, property_id)
            if prop is not None:
                properties[property_id] = prop
        return properties

    @staticmethod
    def _build_timeline(buyer_requirements, property_interests, activities, properties_by_id) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []

        for activity in activities:
            events.append(
                TimelineEvent(
                    event_type="activity",
                    occurred_at=activity.occurred_at,
                    summary=f"{activity.activity_type}: {activity.notes}",
                    related_id=activity.id,
                )
            )

        for pi in property_interests:
            prop = properties_by_id.get(pi.property_id)
            title = prop.title if prop is not None else "a property"
            events.append(
                TimelineEvent(
                    event_type="property_interest",
                    occurred_at=pi.created_at,
                    summary=_property_interest_summary(pi, title),
                    related_id=pi.id,
                )
            )

        for br in buyer_requirements:
            events.append(
                TimelineEvent(
                    event_type="buyer_requirement",
                    occurred_at=br.created_at,
                    summary=_buyer_requirement_summary(br),
                    related_id=br.id,
                )
            )

        events.sort(key=lambda e: e.occurred_at)
        return events

    @staticmethod
    def _engagement_summary(buyer_requirements, property_interests, activities_asc) -> EngagementSummary:
        last_activity_at = activities_asc[-1].occurred_at if activities_asc else None
        days_since_last_activity = None
        if last_activity_at is not None:
            now = datetime.now(timezone.utc)
            # SQLite (unlike Postgres) drops tzinfo on round-trip even for a
            # DateTime(timezone=True) column — subtracting an aware `now`
            # from a naive value read back in tests would raise TypeError.
            reference = last_activity_at if last_activity_at.tzinfo is not None else last_activity_at.replace(tzinfo=timezone.utc)
            days_since_last_activity = (now - reference).days
        return EngagementSummary(
            activity_count=len(activities_asc),
            last_activity_at=last_activity_at,
            days_since_last_activity=days_since_last_activity,
            has_active_buyer_requirement=any(br.status == "active" for br in buyer_requirements),
            active_property_interest_count=sum(
                1 for pi in property_interests if pi.status in _ACTIVE_PROPERTY_INTEREST_STATUSES
            ),
        )
