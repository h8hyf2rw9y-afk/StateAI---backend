"""
The explicit action layer (app/automation/actions.py) — Phase 5. Every
action must be organization-scoped, validated, audited, and predictable on
failure; create_notification must additionally be idempotent (never a
duplicate for the same related entity).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.automation import actions
from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.notification import Notification
from app.models.opportunity import Opportunity
from app.models.organization import Organization, User
from app.models.task import Task


def _make_contact(db: Session, organization_id: uuid.UUID, **overrides) -> Contact:
    contact = Contact(
        organization_id=organization_id,
        first_name=overrides.pop("first_name", "Beatriz"),
        last_name=overrides.pop("last_name", "QA"),
        email=overrides.pop("email", "beatriz.qa@example.com"),
        **overrides,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


class TestCreateTask:
    def test_creates_a_real_task_with_an_audit_entry(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        due = datetime.now(timezone.utc) + timedelta(days=1)

        task = actions.create_task(
            db_session,
            organization_id,
            assigned_to_user_id=current_user.id,
            title="Follow up with Beatriz",
            task_type="follow_up",
            due_at=due,
            contact_id=contact.id,
            actor_user_id=None,
        )

        assert task.title == "Follow up with Beatriz"
        assert task.assigned_to_user_id == current_user.id
        assert task.contact_id == contact.id

        entries = db_session.query(AuditLog).filter(AuditLog.entity_id == task.id).all()
        assert len(entries) == 1
        assert entries[0].action == "TASK_CREATED"
        assert entries[0].actor_user_id is None  # system-created, per the nullable-actor convention

    def test_rejects_a_contact_from_another_organization(self, db_session, organization_id, current_user):
        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        db_session.commit()
        other_contact = _make_contact(db_session, other_org.id)

        with pytest.raises(HTTPException) as exc_info:
            actions.create_task(
                db_session,
                organization_id,
                assigned_to_user_id=current_user.id,
                title="x",
                task_type="follow_up",
                due_at=datetime.now(timezone.utc),
                contact_id=other_contact.id,
            )
        assert exc_info.value.status_code == 404


class TestCreateActivity:
    def test_creates_a_real_activity_with_an_audit_entry(self, db_session, organization_id):
        contact = _make_contact(db_session, organization_id)

        activity = actions.create_activity(
            db_session,
            organization_id,
            contact_id=contact.id,
            activity_type="property_viewing",
            notes="Liked the property but wants to compare two more.",
            occurred_at=datetime.now(timezone.utc),
        )

        assert activity.notes == "Liked the property but wants to compare two more."
        assert activity.contact_id == contact.id

        entries = db_session.query(AuditLog).filter(AuditLog.entity_id == activity.id).all()
        assert len(entries) == 1
        assert entries[0].action == "ACTIVITY_CREATED"


class TestUpdateOpportunityStage:
    def test_updates_the_stage_and_records_the_existing_stage_change_hooks(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        opportunity = Opportunity(
            organization_id=organization_id,
            contact_id=contact.id,
            opportunity_type="buy",
            stage="qualification",
            title="Test opportunity",
        )
        db_session.add(opportunity)
        db_session.commit()

        updated = actions.update_opportunity_stage(
            db_session, organization_id, opportunity_id=opportunity.id, stage="search", actor_user_id=current_user.id
        )

        assert updated.stage == "search"
        entries = db_session.query(AuditLog).filter(AuditLog.entity_id == opportunity.id).all()
        assert any(e.action == "OPPORTUNITY_STAGE_CHANGED" for e in entries)


def _make_appointment(db: Session, organization_id: uuid.UUID, **overrides) -> Appointment:
    start_at = overrides.pop("start_at", datetime.now(timezone.utc) - timedelta(days=1))
    appointment = Appointment(
        organization_id=organization_id,
        title=overrides.pop("title", "Showing"),
        appointment_type=overrides.pop("appointment_type", "showing"),
        status=overrides.pop("status", "completed"),
        start_at=start_at,
        end_at=overrides.pop("end_at", start_at + timedelta(hours=1)),
        **overrides,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment


class TestCreateCompletedAppointmentFollowupTask:
    """Phase 7 — the project's first Level-2 (controlled automation) CRM write."""

    def test_creates_a_real_task_with_deterministic_content_and_an_audit_entry(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        appointment = _make_appointment(db_session, organization_id, contact_id=contact.id, assigned_to_user_id=current_user.id)

        task = actions.create_completed_appointment_followup_task(db_session, organization_id, appointment=appointment)

        assert task is not None
        assert task.title == "Review completed showing outcome and follow up with client"
        assert task.task_type == "follow_up"
        assert task.contact_id == contact.id
        assert task.assigned_to_user_id == current_user.id

        task_audit = db_session.query(AuditLog).filter(AuditLog.entity_id == task.id, AuditLog.action == "TASK_CREATED").one_or_none()
        assert task_audit is not None

        marker_audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.entity_id == appointment.id, AuditLog.action == "APPOINTMENT_FOLLOWUP_TASK_CREATED")
            .one_or_none()
        )
        assert marker_audit is not None

    def test_also_creates_a_companion_notification_linking_to_the_task(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id, first_name="Ana", last_name="QA")
        appointment = _make_appointment(db_session, organization_id, contact_id=contact.id, assigned_to_user_id=current_user.id)

        task = actions.create_completed_appointment_followup_task(db_session, organization_id, appointment=appointment)

        notification = db_session.query(Notification).filter(Notification.related_entity_id == task.id).one_or_none()
        assert notification is not None
        assert notification.type == "followup_task_created"
        assert notification.related_entity_type == "task"
        assert notification.user_id == current_user.id
        assert "Ana QA" in notification.body
        assert str(appointment.id) not in notification.body  # no raw UUID exposure

    def test_returns_none_and_creates_nothing_when_already_processed(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        appointment = _make_appointment(db_session, organization_id, contact_id=contact.id, assigned_to_user_id=current_user.id)

        first = actions.create_completed_appointment_followup_task(db_session, organization_id, appointment=appointment)
        second = actions.create_completed_appointment_followup_task(db_session, organization_id, appointment=appointment)

        assert first is not None
        assert second is None
        assert db_session.query(Task).filter(Task.contact_id == contact.id).count() == 1

    def test_returns_none_when_the_appointment_has_no_contact(self, db_session, organization_id, current_user):
        appointment = _make_appointment(db_session, organization_id, contact_id=None, assigned_to_user_id=current_user.id)
        assert actions.create_completed_appointment_followup_task(db_session, organization_id, appointment=appointment) is None

    def test_falls_back_to_the_linked_opportunitys_owner_when_unassigned(self, db_session, organization_id, current_user):
        contact = _make_contact(db_session, organization_id)
        opportunity = Opportunity(
            organization_id=organization_id, contact_id=contact.id, opportunity_type="buy",
            stage="showing", title="Test opportunity", owner_user_id=current_user.id,
        )
        db_session.add(opportunity)
        db_session.commit()
        appointment = _make_appointment(db_session, organization_id, contact_id=contact.id, assigned_to_user_id=None, opportunity_id=opportunity.id)

        task = actions.create_completed_appointment_followup_task(db_session, organization_id, appointment=appointment)

        assert task is not None
        assert task.assigned_to_user_id == current_user.id
        assert task.opportunity_id == opportunity.id

    def test_returns_none_when_no_assignee_can_be_found(self, db_session, organization_id):
        contact = _make_contact(db_session, organization_id)
        appointment = _make_appointment(db_session, organization_id, contact_id=contact.id, assigned_to_user_id=None)
        assert actions.create_completed_appointment_followup_task(db_session, organization_id, appointment=appointment) is None

    def test_never_calls_an_llm_or_aigateway(self, db_session, organization_id, current_user):
        """Structural safety check — this whole module must remain import-free of any AI/LLM dependency."""
        import app.automation.actions as actions_module

        source_names = dir(actions_module)
        assert "AIGateway" not in source_names
        assert "LLMProvider" not in source_names


class TestCreateNotification:
    def test_creates_a_real_notification_with_an_audit_entry(self, db_session, organization_id, current_user):
        notification = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="Task overdue",
            body="Follow up with Beatriz is overdue.",
            related_entity_type="task",
            related_entity_id=uuid.uuid4(),
        )

        assert notification is not None
        assert notification.type == "task_due"
        entries = db_session.query(AuditLog).filter(AuditLog.entity_id == notification.id).all()
        assert len(entries) == 1
        assert entries[0].action == "NOTIFICATION_CREATED"
        assert entries[0].actor_user_id is None

    def test_deduplicates_on_the_exact_same_related_entity(self, db_session, organization_id, current_user):
        task_id = uuid.uuid4()

        first = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="Task overdue",
            body="x",
            related_entity_type="task",
            related_entity_id=task_id,
        )
        second = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="Task overdue",
            body="x",
            related_entity_type="task",
            related_entity_id=task_id,
        )

        assert first is not None
        assert second is None  # a no-op, not an error, not a duplicate row
        count = db_session.query(Notification).filter(Notification.related_entity_id == task_id).count()
        assert count == 1

    def test_a_different_related_entity_is_not_deduplicated(self, db_session, organization_id, current_user):
        first = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="x",
            body="x",
            related_entity_type="task",
            related_entity_id=uuid.uuid4(),
        )
        second = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="x",
            body="x",
            related_entity_type="task",
            related_entity_id=uuid.uuid4(),
        )

        assert first is not None
        assert second is not None

    def test_a_notification_already_marked_read_is_still_not_recreated(self, db_session, organization_id, current_user):
        """Dedup must not consider read_at — a dismissed notification about a still-overdue task must not reappear."""
        task_id = uuid.uuid4()
        first = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="x",
            body="x",
            related_entity_type="task",
            related_entity_id=task_id,
        )
        first.read_at = datetime.now(timezone.utc)
        db_session.commit()

        second = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="x",
            body="x",
            related_entity_type="task",
            related_entity_id=task_id,
        )
        assert second is None

    def test_cross_organization_notifications_never_collide(self, db_session, organization_id, current_user):
        """Same related_entity_id, different organization — must not be treated as the same event."""
        other_org = Organization(name="Other Org")
        db_session.add(other_org)
        db_session.commit()
        other_user_id = uuid.uuid4()
        db_session.add(User(id=other_user_id, organization_id=other_org.id, role="agent"))
        db_session.commit()

        task_id = uuid.uuid4()
        first = actions.create_notification(
            db_session,
            organization_id,
            user_id=current_user.id,
            notification_type="task_due",
            title="x",
            body="x",
            related_entity_type="task",
            related_entity_id=task_id,
        )
        second = actions.create_notification(
            db_session,
            other_org.id,
            user_id=other_user_id,
            notification_type="task_due",
            title="x",
            body="x",
            related_entity_type="task",
            related_entity_id=task_id,
        )
        assert first is not None
        assert second is not None
