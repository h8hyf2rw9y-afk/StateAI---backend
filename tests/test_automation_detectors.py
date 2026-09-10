"""
Event detection (app/automation/detectors.py) — Phase 5. Every test passes
an explicit `now` so boundaries are exact and deterministic, never
dependent on the real wall clock.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.automation.detectors import (
    UPCOMING_APPOINTMENT_WINDOW,
    detect_overdue_tasks,
    detect_upcoming_appointments,
    run_detectors_for_organization,
)
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.notification import Notification
from app.models.task import Task

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


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


def _make_appointment(db: Session, organization_id: uuid.UUID, user_id, *, start_at: datetime, status: str = "confirmed", contact_id=None) -> Appointment:
    appointment = Appointment(
        organization_id=organization_id,
        assigned_to_user_id=user_id,
        contact_id=contact_id,
        title="Showing",
        appointment_type="showing",
        status=status,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )
    db.add(appointment)
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


class TestRunDetectorsForOrganization:
    def test_reports_counts_for_both_detectors(self, db_session, organization_id, current_user):
        _make_task(db_session, organization_id, current_user.id, due_at=NOW - timedelta(days=1))
        _make_appointment(db_session, organization_id, current_user.id, start_at=NOW + timedelta(hours=2))

        counts = run_detectors_for_organization(db_session, organization_id, now=NOW)

        assert counts == {"task_due": 1, "appointment_upcoming": 1}

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
        assert counts == {"task_due": 0, "appointment_upcoming": 0}
