from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.property_interest import PropertyInterest
from app.repositories.activity_repo import ActivityRepository
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.buyer_requirement_repo import BuyerRequirementRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.opportunity_repo import OpportunityRepository
from app.repositories.property_interest_repo import PropertyInterestRepository
from app.repositories.property_repo import PropertyRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.enums import OPPORTUNITY_CLOSED_STAGES
from app.schemas.lead_context import (
    ActivityContext,
    AppointmentContext,
    BuyerRequirementContext,
    ContactContext,
    EngagementSummary,
    LeadContext,
    OpportunityBuyerRequirementSummary,
    OpportunityContext,
    OpportunityPropertySummary,
    PropertyContext,
    PropertyInterestContext,
    TaskContext,
    TimelineEvent,
)

# Property interest statuses that count as "still open" for engagement_summary —
# lost/won/not_interested are resolved outcomes, not ongoing engagement.
_ACTIVE_PROPERTY_INTEREST_STATUSES = {
    "new", "contacted", "interested", "viewing_scheduled", "viewed", "offer", "negotiation",
}
# Task statuses that still represent open work — completed/cancelled don't.
_OPEN_TASK_STATUSES = {"pending", "in_progress"}
# Appointment statuses that still represent a real future commitment —
# cancelled/completed/no_show don't, regardless of start_at.
_UPCOMING_APPOINTMENT_STATUSES = {"scheduled", "confirmed"}


def _buyer_requirement_summary(br: BuyerRequirement) -> str:
    kind = br.property_type or "property"
    return f"Buyer requirement created ({kind}, status={br.status})"


def _property_interest_summary(pi: PropertyInterest, property_title: str) -> str:
    return f"Interested in {property_title} (status={pi.status})"


def _opportunity_summary(opportunity: Opportunity) -> str:
    return f"Opportunity created ({opportunity.opportunity_type}, stage={opportunity.stage})"


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite (unlike Postgres) drops tzinfo on round-trip even for a DateTime(timezone=True) column — subtracting/comparing an aware `now` against a naive value read back in tests would raise TypeError. Same quirk app/services/appointment_service.py already works around."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class LeadContextService:
    """
    Assembles the structured "everything relevant about this lead" object —
    see app/schemas/lead_context.py for why it's a typed tree, not text.
    This is the Backend Service layer in the required
    AI Agent -> AI Tool -> Backend Service -> Repository -> Supabase flow;
    app/ai/lead_context_tool.py is the thin AI Tool wrapper around it.

    Opportunities (and the Tasks/Appointments linked to them) are assembled
    here the same way Buyer Requirements/Property Interests/Activities
    always have been: one repository call per entity, composed in Python —
    no second context-building mechanism, no N+1 per-opportunity queries
    (Task/Appointment/Activity lists are fetched once each for the whole
    contact, then filtered in memory per opportunity in _opportunity_context).
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.contact_repo = ContactRepository(db)
        self.buyer_requirement_repo = BuyerRequirementRepository(db)
        self.property_interest_repo = PropertyInterestRepository(db)
        self.activity_repo = ActivityRepository(db)
        self.property_repo = PropertyRepository(db)
        self.opportunity_repo = OpportunityRepository(db)
        self.task_repo = TaskRepository(db)
        self.appointment_repo = AppointmentRepository(db)

    def build(
        self,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        activity_limit: int = 20,
        task_limit: int = 20,
        appointment_limit: int = 20,
    ) -> LeadContext:
        contact = self._get_contact_or_404(organization_id, contact_id)

        buyer_requirements = self.buyer_requirement_repo.list_for_contact(organization_id, contact_id)
        property_interests = self.property_interest_repo.list_for_contact(organization_id, contact_id)
        # Ascending (oldest first) — see ActivityRepository.list_for_contact.
        activities_asc = self.activity_repo.list_for_contact(organization_id, contact_id)
        # All of them, including won/lost — a contact's history (including
        # deals that didn't work out) is real context, not noise to discard.
        opportunities = self.opportunity_repo.list_for_contact(organization_id, contact_id)
        opportunity_ids = [o.id for o in opportunities]
        # contact_id OR linked-opportunity — a task/appointment about one of
        # this contact's opportunities may not have its own contact_id set
        # (the two fields are independent); see TaskRepository.list_for_contact.
        tasks = self.task_repo.list_for_contact(
            organization_id, contact_id, opportunity_ids=opportunity_ids, limit=task_limit
        )
        appointments = self.appointment_repo.list_for_contact(
            organization_id, contact_id, opportunity_ids=opportunity_ids, limit=appointment_limit
        )

        properties_by_id = self._load_referenced_properties(organization_id, property_interests, activities_asc, opportunities)
        buyer_requirements_by_id = {br.id: br for br in buyer_requirements}

        recent_activities = list(reversed(activities_asc))[:activity_limit] if activity_limit > 0 else []

        return LeadContext(
            contact=self._contact_context(contact),
            buyer_requirements=[BuyerRequirementContext.model_validate(br) for br in buyer_requirements],
            property_interests=[PropertyInterestContext.model_validate(pi) for pi in property_interests],
            properties=[PropertyContext.model_validate(p) for p in properties_by_id.values()],
            opportunities=[
                self._opportunity_context(o, properties_by_id, buyer_requirements_by_id, activities_asc, tasks, appointments)
                for o in opportunities
            ],
            activities=[ActivityContext.model_validate(a) for a in recent_activities],
            tasks=[TaskContext.model_validate(t) for t in tasks],
            appointments=[AppointmentContext.model_validate(a) for a in appointments],
            timeline=self._build_timeline(buyer_requirements, property_interests, opportunities, activities_asc, properties_by_id),
            engagement_summary=self._engagement_summary(
                buyer_requirements, property_interests, opportunities, activities_asc, tasks, appointments
            ),
            generated_at=datetime.now(timezone.utc),
        )

    def compute_context_fingerprint(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> dict:
        """
        A small, deterministic summary of "how fresh is this contact's data
        right now" — built from the exact same repository calls build() uses
        (so it can never define "what matters" any differently than the
        context an agent actually receives; see this class's own docstring
        and the three agent files, which all embed the *entire* LeadContext
        into their prompt). Deliberately NOT the LeadContext object itself —
        it only needs each entity list's size and most recent modification
        time, not the data, to tell "did anything change" apart from "what
        changed." Used to detect staleness of a previously stored
        AgentExecution without duplicating CRM data into agent_executions
        (see app/models/agent_execution.py's input_snapshot column and
        AgentExecutionService.record_success).

        Every referenced model (Contact, BuyerRequirement, PropertyInterest,
        Property, Opportunity, Task, Appointment) uses TimestampMixin, so
        `updated_at` is always real at the ORM level even though the
        LeadContext *read schema* doesn't expose it for every nested type —
        this method reads the ORM objects directly, not the Pydantic tree,
        so that schema gap doesn't limit it. Activities have no
        `updated_at` (they're an append-only log — see Activity's own
        model), so `created_at` stands in for "most recent change" there;
        a new activity is the only way that list ever changes.
        """
        contact = self._get_contact_or_404(organization_id, contact_id)

        buyer_requirements = self.buyer_requirement_repo.list_for_contact(organization_id, contact_id)
        property_interests = self.property_interest_repo.list_for_contact(organization_id, contact_id)
        activities = self.activity_repo.list_for_contact(organization_id, contact_id)
        opportunities = self.opportunity_repo.list_for_contact(organization_id, contact_id)
        opportunity_ids = [o.id for o in opportunities]
        tasks = self.task_repo.list_for_contact(organization_id, contact_id, opportunity_ids=opportunity_ids, limit=1000)
        appointments = self.appointment_repo.list_for_contact(
            organization_id, contact_id, opportunity_ids=opportunity_ids, limit=1000
        )
        properties_by_id = self._load_referenced_properties(organization_id, property_interests, activities, opportunities)

        def _bucket(items, *, timestamp_attr: str) -> dict:
            timestamps = [getattr(item, timestamp_attr) for item in items]
            return {
                "count": len(items),
                "latest": max(timestamps).isoformat() if timestamps else None,
            }

        return {
            "contact_updated_at": contact.updated_at.isoformat(),
            "buyer_requirements": _bucket(buyer_requirements, timestamp_attr="updated_at"),
            "property_interests": _bucket(property_interests, timestamp_attr="updated_at"),
            "properties": _bucket(list(properties_by_id.values()), timestamp_attr="updated_at"),
            "opportunities": _bucket(opportunities, timestamp_attr="updated_at"),
            "tasks": _bucket(tasks, timestamp_attr="updated_at"),
            "appointments": _bucket(appointments, timestamp_attr="updated_at"),
            "activities": _bucket(activities, timestamp_attr="created_at"),
        }

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

    def _load_referenced_properties(
        self, organization_id, property_interests, activities, opportunities
    ) -> dict[uuid.UUID, object]:
        property_ids = {pi.property_id for pi in property_interests}
        property_ids |= {a.property_id for a in activities if a.property_id is not None}
        property_ids |= {o.property_id for o in opportunities if o.property_id is not None}

        properties: dict[uuid.UUID, object] = {}
        for property_id in property_ids:
            prop = self.property_repo.get(organization_id, property_id)
            if prop is not None:
                properties[property_id] = prop
        return properties

    @staticmethod
    def _opportunity_context(
        opportunity: Opportunity, properties_by_id, buyer_requirements_by_id, activities, tasks, appointments
    ) -> OpportunityContext:
        prop = properties_by_id.get(opportunity.property_id) if opportunity.property_id else None
        requirement = (
            buyer_requirements_by_id.get(opportunity.buyer_requirement_id) if opportunity.buyer_requirement_id else None
        )
        return OpportunityContext(
            id=opportunity.id,
            contact_id=opportunity.contact_id,
            opportunity_type=opportunity.opportunity_type,
            stage=opportunity.stage,
            is_active=opportunity.stage not in OPPORTUNITY_CLOSED_STAGES,
            title=opportunity.title,
            description=opportunity.description,
            expected_value=opportunity.expected_value,
            currency=opportunity.currency,
            probability=opportunity.probability,
            expected_close_date=opportunity.expected_close_date,
            closed_at=opportunity.closed_at,
            lost_reason=opportunity.lost_reason,
            owner_user_id=opportunity.owner_user_id,
            created_at=opportunity.created_at,
            updated_at=opportunity.updated_at,
            property=OpportunityPropertySummary.model_validate(prop) if prop is not None else None,
            buyer_requirement=(
                OpportunityBuyerRequirementSummary.model_validate(requirement) if requirement is not None else None
            ),
            activity_ids=[a.id for a in activities if a.opportunity_id == opportunity.id],
            task_ids=[t.id for t in tasks if t.opportunity_id == opportunity.id],
            appointment_ids=[a.id for a in appointments if a.opportunity_id == opportunity.id],
        )

    @staticmethod
    def _build_timeline(buyer_requirements, property_interests, opportunities, activities, properties_by_id) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []

        for activity in activities:
            events.append(
                TimelineEvent(
                    event_type="activity",
                    occurred_at=activity.occurred_at,
                    # A stage-change Activity (activity_type="stage_change",
                    # written by OpportunityService) flows in right here,
                    # through the same generic path as every other Activity
                    # — no separate "opportunity stage change" event_type;
                    # see app/schemas/lead_context.py's TimelineEvent docstring.
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

        for o in opportunities:
            events.append(
                TimelineEvent(
                    event_type="opportunity",
                    occurred_at=o.created_at,
                    summary=_opportunity_summary(o),
                    related_id=o.id,
                )
            )

        events.sort(key=lambda e: e.occurred_at)
        return events

    @staticmethod
    def _engagement_summary(buyer_requirements, property_interests, opportunities, activities_asc, tasks, appointments) -> EngagementSummary:
        last_activity_at = activities_asc[-1].occurred_at if activities_asc else None
        days_since_last_activity = None
        now = datetime.now(timezone.utc)
        if last_activity_at is not None:
            days_since_last_activity = (now - _as_aware_utc(last_activity_at)).days

        return EngagementSummary(
            activity_count=len(activities_asc),
            last_activity_at=last_activity_at,
            days_since_last_activity=days_since_last_activity,
            has_active_buyer_requirement=any(br.status == "active" for br in buyer_requirements),
            active_property_interest_count=sum(
                1 for pi in property_interests if pi.status in _ACTIVE_PROPERTY_INTEREST_STATUSES
            ),
            active_opportunity_count=sum(1 for o in opportunities if o.stage not in OPPORTUNITY_CLOSED_STAGES),
            won_opportunity_count=sum(1 for o in opportunities if o.stage == "won"),
            lost_opportunity_count=sum(1 for o in opportunities if o.stage == "lost"),
            pending_task_count=sum(1 for t in tasks if t.status in _OPEN_TASK_STATUSES),
            overdue_task_count=sum(
                1 for t in tasks if t.status in _OPEN_TASK_STATUSES and _as_aware_utc(t.due_at) < now
            ),
            upcoming_appointment_count=sum(
                1
                for a in appointments
                if a.status in _UPCOMING_APPOINTMENT_STATUSES and _as_aware_utc(a.start_at) > now
            ),
        )
