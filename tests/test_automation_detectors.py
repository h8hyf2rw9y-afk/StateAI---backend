"""
Event detection (app/automation/detectors.py) — Phase 5. Every test passes
an explicit `now` so boundaries are exact and deterministic, never
dependent on the real wall clock.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.automation.actions import COMPLETED_SHOWING_FOLLOWUP_DAYS
from app.automation.detectors import (
    OPPORTUNITY_INACTIVITY_THRESHOLD,
    UPCOMING_APPOINTMENT_WINDOW,
    detect_completed_appointments_needing_followup,
    detect_contacts_missing_requirements,
    detect_inactive_opportunities,
    detect_incomplete_buyer_requirements,
    detect_overdue_tasks,
    detect_upcoming_appointments,
    run_detectors_for_organization,
)
from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.buyer_requirement import BuyerRequirement, BuyerRequirementLocation
from app.models.contact import Contact
from app.models.notification import Notification
from app.models.opportunity import Opportunity
from app.models.task import Task

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _make_buyer_requirement(db: Session, organization_id: uuid.UUID, contact_id: uuid.UUID, **overrides) -> BuyerRequirement:
    requirement = BuyerRequirement(
        organization_id=organization_id,
        contact_id=contact_id,
        status=overrides.pop("status", "active"),
        property_type=overrides.pop("property_type", "house"),
        budget_min=overrides.pop("budget_min", 1_000_000),
        **overrides,
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement


def _make_opportunity(db: Session, organization_id: uuid.UUID, contact_id: uuid.UUID, *, owner_user_id, updated_at: datetime, stage: str = "offer") -> Opportunity:
    opportunity = Opportunity(
        organization_id=organization_id,
        contact_id=contact_id,
        opportunity_type="buy",
        stage=stage,
        title="House for the Ramírez family",
        owner_user_id=owner_user_id,
    )
    db.add(opportunity)
    db.commit()
    # updated_at is auto-stamped on insert/update by TimestampMixin — set it
    # directly and re-flush so the detector sees a controlled, backdated value,
    # mirroring how the appointment/task fixtures above control their own clock.
    db.query(Opportunity).filter(Opportunity.id == opportunity.id).update({"updated_at": updated_at})
    db.commit()
    db.refresh(opportunity)
    return opportunity


def _make_contact(db: Session, organization_id: uuid.UUID) -> Contact:
    contact = Contact(organization_id=organization_id, first_name="Beatriz", last_name="QA", email="beatriz.qa@example.com")
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _make_task(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID, *, due_at: datetime, status: str = "pending", contact_id=None) -> Task:
    task = Task(
        organization_id=organization_id,
        assigned_to_user_id=user_id,
        contact_id=contact_id,
        title="Follow up",
        task_type="follow_up",
        status=status,
        due_at=due_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _make_appointment(
    db: Session,
    organization_id: uuid.UUID,
    user_id,
    *,
    start_at: datetime,
    status: str = "confirmed",
    contact_id=None,
    property_id=None,
    opportunity_id=None,
    appointment_type: str = "showing",
    updated_at: datetime | None = None,
) -> Appointment:
    appointment = Appointment(
        organization_id=organization_id,
        assigned_to_user_id=user_id,
        contact_id=contact_id,
        property_id=property_id,
        opportunity_id=opportunity_id,
        title="Showing",
        appointment_type=appointment_type,
        status=status,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )
    db.add(appointment)
    db.commit()
    if updated_at is not None:
        # updated_at is auto-stamped by TimestampMixin — set it directly and
        # re-flush so the detector sees a controlled "completed at" value,
        # mirroring _make_opportunity's identical technique above.
        db.query(Appointment).filter(Appointment.id == appointment.id).update({"updated_at": updated_at})
        db.commit()
    db.refresh(appointment)
    return appointment


class TestDetectOverdueTasks:
    def test_finds_a_task_past_its_due_date(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        task = _make_task(db_session, organization_id, current_user.id, due_at=NOW - timedelta(days=1), contact_id=contact.id)

        created = detect_overdue_tasks(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].related_entity_id == task.id
        assert "Beatriz" in created[0].body

    def test_ignores_a_task_due_in_the_future(self, db_session, organization_id, current_user):
        _make_task(db_session, organization_id, current_user.id, due_at=NOW + timedelta(days=1))
        assert detect_overdue_tasks(db_session, organization_id, now=NOW) == []

    def test_ignores_a_completed_task_even_if_its_due_date_has_passed(self, db_session, organization_id, current_user):
        _make_task(db_session, organization_id, current_user.id, due_at=NOW - timedelta(days=1), status="completed")
        assert detect_overdue_tasks(db_session, organization_id, now=NOW) == []

    def test_ignores_a_cancelled_task(self, db_session, organization_id, current_user):
        _make_task(db_session, organization_id, current_user.id, due_at=NOW - timedelta(days=1), status="cancelled")
        assert detect_overdue_tasks(db_session, organization_id, now=NOW) == []

    def test_a_task_due_exactly_now_is_not_yet_overdue(self, db_session, organization_id, current_user):
        """Boundary check: due_at == now is not "in the past" yet."""
        _make_task(db_session, organization_id, current_user.id, due_at=NOW)
        assert detect_overdue_tasks(db_session, organization_id, now=NOW) == []

    def test_running_twice_creates_no_duplicate_notification(self, db_session, organization_id, current_user):
        _make_task(db_session, organization_id, current_user.id, due_at=NOW - timedelta(days=1))

        first = detect_overdue_tasks(db_session, organization_id, now=NOW)
        second = detect_overdue_tasks(db_session, organization_id, now=NOW + timedelta(minutes=5))

        assert len(first) == 1
        assert len(second) == 0
        assert db_session.query(Notification).filter(Notification.type == "task_due").count() == 1


class TestDetectUpcomingAppointments:
    def test_finds_an_appointment_within_the_window(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        appointment = _make_appointment(
            db_session, organization_id, current_user.id, start_at=NOW + timedelta(hours=2), contact_id=contact.id
        )

        created = detect_upcoming_appointments(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].related_entity_id == appointment.id
        assert "Beatriz" in created[0].body

    def test_ignores_an_appointment_beyond_the_window(self, db_session, organization_id, current_user):
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW + UPCOMING_APPOINTMENT_WINDOW + timedelta(hours=1))
        assert detect_upcoming_appointments(db_session, organization_id, now=NOW) == []

    def test_ignores_an_appointment_already_in_the_past(self, db_session, organization_id, current_user):
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW - timedelta(hours=1))
        assert detect_upcoming_appointments(db_session, organization_id, now=NOW) == []

    def test_ignores_a_cancelled_appointment(self, db_session, organization_id, current_user):
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW + timedelta(hours=2), status="cancelled")
        assert detect_upcoming_appointments(db_session, organization_id, now=NOW) == []

    def test_skips_an_appointment_with_no_assignee_rather_than_guessing_one(self, db_session, organization_id):
        _make_appointment(db_session, organization_id, None, start_at=NOW + timedelta(hours=2))
        assert detect_upcoming_appointments(db_session, organization_id, now=NOW) == []

    def test_running_twice_creates_no_duplicate_notification(self, db_session, organization_id, current_user):
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW + timedelta(hours=2))

        first = detect_upcoming_appointments(db_session, organization_id, now=NOW)
        second = detect_upcoming_appointments(db_session, organization_id, now=NOW + timedelta(minutes=5))

        assert len(first) == 1
        assert len(second) == 0
        assert db_session.query(Notification).filter(Notification.type == "appointment_upcoming").count() == 1


class TestDetectContactsMissingRequirements:
    def test_flags_a_contact_with_no_buyer_requirement(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)

        created = detect_contacts_missing_requirements(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].related_entity_type == "contact"
        assert created[0].related_entity_id == contact.id
        assert created[0].type == "contact_missing_requirements"
        assert "Beatriz QA" in created[0].body

    def test_ignores_a_contact_that_already_has_a_buyer_requirement(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_buyer_requirement(db_session, organization_id, contact.id)

        assert detect_contacts_missing_requirements(db_session, organization_id, now=NOW) == []

    def test_a_contact_with_only_a_cancelled_requirement_still_counts_as_having_one(self, db_session, organization_id, current_user):
        """Any requirement row at all — even cancelled — proves qualification was already started; see the detector's own docstring."""
        contact = _make_contact(db_session, organization_id)
        _make_buyer_requirement(db_session, organization_id, contact.id, status="cancelled")

        assert detect_contacts_missing_requirements(db_session, organization_id, now=NOW) == []

    def test_running_twice_creates_no_duplicate_notification(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)

        first = detect_contacts_missing_requirements(db_session, organization_id, now=NOW)
        second = detect_contacts_missing_requirements(db_session, organization_id, now=NOW)

        assert len(first) == 1
        assert len(second) == 0
        assert (
            db_session.query(Notification)
            .filter(Notification.type == "contact_missing_requirements", Notification.related_entity_id == contact.id)
            .count()
            == 1
        )

    def test_is_organization_scoped(self, db_session, organization_id, current_user):
        from app.models.organization import Organization, User

        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        db_session.commit()
        other_user_id = uuid.uuid4()
        db_session.add(User(id=other_user_id, organization_id=other_org.id, role="agent"))
        db_session.commit()
        _make_contact(db_session, other_org.id)

        assert detect_contacts_missing_requirements(db_session, organization_id, now=NOW) == []


class TestDetectIncompleteBuyerRequirements:
    def test_flags_a_requirement_missing_required_fields(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        requirement = _make_buyer_requirement(db_session, organization_id, contact.id, property_type=None, budget_min=None)

        created = detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].type == "buyer_requirement_incomplete"
        assert created[0].related_entity_type == "buyer_requirement"
        assert created[0].related_entity_id == requirement.id
        assert "property type" in created[0].body
        assert "budget" in created[0].body
        assert "location" in created[0].body

    def test_a_complete_requirement_is_marked_ready_for_matching(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        requirement = _make_buyer_requirement(db_session, organization_id, contact.id)
        db_session.add(BuyerRequirementLocation(buyer_requirement_id=requirement.id, city="Mexico City"))
        db_session.commit()

        created = detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].type == "buyer_requirement_ready"
        assert "ready" in created[0].body.lower() or "Buyer Matching" in created[0].body

    def test_ignores_a_paused_requirement(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_buyer_requirement(db_session, organization_id, contact.id, status="paused", property_type=None)

        assert detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW) == []

    def test_transition_from_incomplete_to_complete_produces_both_notifications(self, db_session, organization_id, current_user):
        """Different `type` values, so no dedup collision — the agent is told both times."""
        contact = _make_contact(db_session, organization_id)
        requirement = _make_buyer_requirement(db_session, organization_id, contact.id, property_type=None, budget_min=None)

        first = detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW)
        assert len(first) == 1
        assert first[0].type == "buyer_requirement_incomplete"

        requirement.property_type = "house"
        requirement.budget_min = 1_000_000
        db_session.add(BuyerRequirementLocation(buyer_requirement_id=requirement.id, city="Mexico City"))
        db_session.commit()

        second = detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW)
        assert len(second) == 1
        assert second[0].type == "buyer_requirement_ready"

    def test_running_twice_on_the_same_state_creates_no_duplicate(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        requirement = _make_buyer_requirement(db_session, organization_id, contact.id, property_type=None, budget_min=None)

        first = detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW)
        second = detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW)

        assert len(first) == 1
        assert len(second) == 0
        assert (
            db_session.query(Notification)
            .filter(Notification.type == "buyer_requirement_incomplete", Notification.related_entity_id == requirement.id)
            .count()
            == 1
        )

    def test_is_organization_scoped(self, db_session, organization_id, current_user):
        from app.models.organization import Organization, User

        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        db_session.commit()
        other_user_id = uuid.uuid4()
        db_session.add(User(id=other_user_id, organization_id=other_org.id, role="agent"))
        db_session.commit()
        other_contact = _make_contact(db_session, other_org.id)
        _make_buyer_requirement(db_session, other_org.id, other_contact.id, property_type=None)

        assert detect_incomplete_buyer_requirements(db_session, organization_id, now=NOW) == []


class TestDetectInactiveOpportunities:
    def test_flags_an_opportunity_untouched_past_the_threshold(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        opportunity = _make_opportunity(
            db_session, organization_id, contact.id,
            owner_user_id=current_user.id,
            updated_at=NOW - OPPORTUNITY_INACTIVITY_THRESHOLD - timedelta(days=1),
        )

        created = detect_inactive_opportunities(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].related_entity_id == opportunity.id
        assert created[0].type == "opportunity_inactive"

    def test_ignores_an_opportunity_updated_recently(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_opportunity(
            db_session, organization_id, contact.id,
            owner_user_id=current_user.id,
            updated_at=NOW - timedelta(days=1),
        )
        assert detect_inactive_opportunities(db_session, organization_id, now=NOW) == []

    def test_just_before_the_threshold_is_not_yet_inactive(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_opportunity(
            db_session, organization_id, contact.id,
            owner_user_id=current_user.id,
            updated_at=NOW - OPPORTUNITY_INACTIVITY_THRESHOLD + timedelta(hours=1),
        )
        assert detect_inactive_opportunities(db_session, organization_id, now=NOW) == []

    def test_just_after_the_threshold_is_inactive(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_opportunity(
            db_session, organization_id, contact.id,
            owner_user_id=current_user.id,
            updated_at=NOW - OPPORTUNITY_INACTIVITY_THRESHOLD - timedelta(hours=1),
        )
        assert len(detect_inactive_opportunities(db_session, organization_id, now=NOW)) == 1

    def test_a_closed_opportunity_is_excluded_even_if_stale(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_opportunity(
            db_session, organization_id, contact.id,
            owner_user_id=current_user.id,
            updated_at=NOW - OPPORTUNITY_INACTIVITY_THRESHOLD - timedelta(days=30),
            stage="won",
        )
        assert detect_inactive_opportunities(db_session, organization_id, now=NOW) == []

    def test_running_twice_creates_no_duplicate_notification(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        opportunity = _make_opportunity(
            db_session, organization_id, contact.id,
            owner_user_id=current_user.id,
            updated_at=NOW - OPPORTUNITY_INACTIVITY_THRESHOLD - timedelta(days=1),
        )

        first = detect_inactive_opportunities(db_session, organization_id, now=NOW)
        second = detect_inactive_opportunities(db_session, organization_id, now=NOW + timedelta(minutes=5))

        assert len(first) == 1
        assert len(second) == 0
        assert (
            db_session.query(Notification)
            .filter(Notification.type == "opportunity_inactive", Notification.related_entity_id == opportunity.id)
            .count()
            == 1
        )

    def test_is_organization_scoped(self, db_session, organization_id, current_user):
        from app.models.organization import Organization, User

        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        db_session.commit()
        other_user_id = uuid.uuid4()
        db_session.add(User(id=other_user_id, organization_id=other_org.id, role="agent"))
        db_session.commit()
        other_contact = _make_contact(db_session, other_org.id)
        _make_opportunity(
            db_session, other_org.id, other_contact.id,
            owner_user_id=other_user_id,
            updated_at=NOW - OPPORTUNITY_INACTIVITY_THRESHOLD - timedelta(days=1),
        )

        assert detect_inactive_opportunities(db_session, organization_id, now=NOW) == []


class TestDetectCompletedAppointmentsNeedingFollowup:
    # --- detection ---------------------------------------------------------

    def test_a_completed_appointment_gets_a_followup_task(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        appointment = _make_appointment(
            db_session, organization_id, current_user.id,
            start_at=NOW - timedelta(days=2), status="completed", contact_id=contact.id,
            updated_at=NOW - timedelta(days=1),
        )

        created = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)

        assert len(created) == 1
        task = created[0]
        assert task.title == "Review completed showing outcome and follow up with client"
        assert task.description == (
            "Review the outcome of the completed showing and determine the appropriate next follow-up with the client."
        )
        assert task.task_type == "follow_up"
        assert task.contact_id == contact.id
        assert task.assigned_to_user_id == current_user.id
        assert task.organization_id == organization_id
        assert task.due_at == appointment.updated_at + timedelta(days=COMPLETED_SHOWING_FOLLOWUP_DAYS)

    def test_a_scheduled_appointment_is_ignored(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW + timedelta(days=1), status="scheduled", contact_id=contact.id)
        assert detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW) == []

    def test_a_confirmed_appointment_is_ignored(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW + timedelta(days=1), status="confirmed", contact_id=contact.id)
        assert detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW) == []

    def test_a_cancelled_appointment_is_ignored(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW - timedelta(days=1), status="cancelled", contact_id=contact.id)
        assert detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW) == []

    def test_a_no_show_appointment_is_ignored(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW - timedelta(days=1), status="no_show", contact_id=contact.id)
        assert detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW) == []

    def test_a_completed_appointment_with_no_contact_is_skipped_safely(self, db_session, organization_id, current_user):
        """Appointment.contact_id is nullable — must never crash, never fabricate a contact."""
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW - timedelta(days=1), status="completed", contact_id=None)
        assert detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW) == []

    def test_an_already_processed_appointment_is_ignored(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        appointment = _make_appointment(
            db_session, organization_id, current_user.id,
            start_at=NOW - timedelta(days=2), status="completed", contact_id=contact.id,
        )
        first = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)
        assert len(first) == 1

        second = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)
        assert second == []

    def test_is_organization_scoped(self, db_session, organization_id, current_user):
        from app.models.organization import Organization, User

        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        db_session.commit()
        other_user_id = uuid.uuid4()
        db_session.add(User(id=other_user_id, organization_id=other_org.id, role="agent"))
        db_session.commit()
        other_contact = _make_contact(db_session, other_org.id)
        _make_appointment(db_session, other_org.id, other_user_id, start_at=NOW - timedelta(days=1), status="completed", contact_id=other_contact.id)

        assert detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW) == []

    # --- task content / relationships ---------------------------------------

    def test_preserves_property_and_opportunity_relationships_when_present(self, db_session, organization_id, current_user):
        from app.models.property import Property

        contact = _make_contact(db_session, organization_id)
        prop = Property(organization_id=organization_id, title="Casa QA", property_type="house", status="active", city="Monterrey")
        db_session.add(prop)
        db_session.commit()
        opportunity = _make_opportunity(db_session, organization_id, contact.id, owner_user_id=current_user.id, updated_at=NOW)
        appointment = _make_appointment(
            db_session, organization_id, current_user.id,
            start_at=NOW - timedelta(days=1), status="completed", contact_id=contact.id,
            property_id=prop.id, opportunity_id=opportunity.id,
        )

        created = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].property_id == prop.id
        assert created[0].opportunity_id == opportunity.id
        assert created[0].id != appointment.id  # sanity: really is a new Task, not the appointment itself

    def test_falls_back_to_the_opportunitys_owner_when_the_appointment_has_no_assignee(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        opportunity = _make_opportunity(db_session, organization_id, contact.id, owner_user_id=current_user.id, updated_at=NOW)
        _make_appointment(
            db_session, organization_id, None,
            start_at=NOW - timedelta(days=1), status="completed", contact_id=contact.id, opportunity_id=opportunity.id,
        )

        created = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)

        assert len(created) == 1
        assert created[0].assigned_to_user_id == current_user.id

    def test_skipped_safely_when_neither_the_appointment_nor_its_opportunity_has_an_owner(self, db_session, organization_id):
        contact = _make_contact(db_session, organization_id)
        _make_appointment(db_session, organization_id, None, start_at=NOW - timedelta(days=1), status="completed", contact_id=contact.id)
        assert detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW) == []

    # --- idempotency ----------------------------------------------------------

    def test_running_three_times_creates_exactly_one_task(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW - timedelta(days=1), status="completed", contact_id=contact.id)

        first = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)
        second = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)
        third = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)

        assert len(first) == 1
        assert second == []
        assert third == []
        assert db_session.query(Task).filter(Task.task_type == "follow_up", Task.contact_id == contact.id).count() == 1

    # --- safety -----------------------------------------------------------------

    def test_never_touches_opportunity_stage_contact_or_property(self, db_session, organization_id, current_user):
        from app.models.property import Property

        contact = _make_contact(db_session, organization_id)
        prop = Property(organization_id=organization_id, title="Casa QA", property_type="house", status="active", city="Monterrey")
        db_session.add(prop)
        db_session.commit()
        opportunity = _make_opportunity(db_session, organization_id, contact.id, owner_user_id=current_user.id, updated_at=NOW, stage="offer")
        _make_appointment(
            db_session, organization_id, current_user.id,
            start_at=NOW - timedelta(days=1), status="completed", contact_id=contact.id,
            property_id=prop.id, opportunity_id=opportunity.id,
        )

        detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)

        db_session.refresh(contact)
        db_session.refresh(prop)
        db_session.refresh(opportunity)
        assert opportunity.stage == "offer"
        assert contact.first_name == "Beatriz"
        assert prop.title == "Casa QA"

    # --- audit --------------------------------------------------------------

    def test_creates_the_expected_audit_trail(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        appointment = _make_appointment(db_session, organization_id, current_user.id, start_at=NOW - timedelta(days=1), status="completed", contact_id=contact.id)

        created = detect_completed_appointments_needing_followup(db_session, organization_id, now=NOW)
        task = created[0]

        # The Task itself is audited exactly like any other TaskService.create call.
        task_audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.entity_type == "task", AuditLog.entity_id == task.id, AuditLog.action == "TASK_CREATED")
            .one_or_none()
        )
        assert task_audit is not None
        assert task_audit.actor_user_id is None  # system-created, not a human PATCH

        # Plus the appointment-side idempotency marker this detector relies on.
        appointment_audit = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.entity_type == "appointment",
                AuditLog.entity_id == appointment.id,
                AuditLog.action == "APPOINTMENT_FOLLOWUP_TASK_CREATED",
            )
            .one_or_none()
        )
        assert appointment_audit is not None
        assert appointment_audit.organization_id == organization_id


class TestRunDetectorsForOrganization:
    def test_reports_counts_for_every_detector(self, db_session, organization_id, current_user):
        _make_task(db_session, organization_id, current_user.id, due_at=NOW - timedelta(days=1))
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW + timedelta(hours=2))
        _make_contact(db_session, organization_id)

        counts = run_detectors_for_organization(db_session, organization_id, now=NOW)

        assert counts == {
            "task_due": 1,
            "appointment_upcoming": 1,
            "contact_missing_requirements": 1,
            "buyer_requirement_completeness": 0,
            "opportunity_inactive": 0,
            "completed_appointment_followup": 0,
        }

    def test_is_organization_scoped(self, db_session, organization_id, current_user):
        """A task overdue in a different organization must never surface here."""
        from app.models.organization import Organization, User

        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        db_session.commit()
        other_user_id = uuid.uuid4()
        db_session.add(User(id=other_user_id, organization_id=other_org.id, role="agent"))
        db_session.commit()
        _make_task(db_session, other_org.id, other_user_id, due_at=NOW - timedelta(days=1))

        counts = run_detectors_for_organization(db_session, organization_id, now=NOW)
        assert counts == {
            "task_due": 0,
            "appointment_upcoming": 0,
            "contact_missing_requirements": 0,
            "buyer_requirement_completeness": 0,
            "opportunity_inactive": 0,
            "completed_appointment_followup": 0,
        }
