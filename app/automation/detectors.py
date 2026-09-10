"""
Event detection — the DETECT step of EVENT -> DETECT -> CONTEXT -> RULE ->
ACTION -> AUDIT -> NOTIFICATION. Both detectors here are plain, read-only,
deterministic queries: "is this task's due_at in the past" and "is this
appointment's start_at coming up soon" need no LLM call and no CONTEXT/RULE
step beyond that one comparison — see the phase brief's own instruction not
to turn a deterministic event into an unnecessary AI call. The Follow-up
Agent already exists for the actual "what should the advisor do about it"
question; these detectors only decide *whether to notify*, not what to
recommend.

Every detector takes `organization_id` explicitly and only ever queries
within it, takes `now` as an explicit parameter (never computing it
internally) so tests can pass a fixed, controlled time, and only ever
writes through app/automation/actions.create_notification — which is
itself where deduplication is enforced (see that function's own
docstring). Running either detector any number of times, at any interval,
for the same organization can never create more than one notification per
underlying event.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.automation.actions import create_notification
from app.models.notification import Notification
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.task_repo import TaskRepository

# How far ahead "upcoming" looks for an appointment reminder. A plain
# module constant, not a new environment variable — see the phase brief's
# "configurable or clearly documented" allowance and app/core/config.py's
# own precedent of keeping single-purpose tuning knobs as code constants
# until a real reason to vary them per-deployment shows up.
UPCOMING_APPOINTMENT_WINDOW = timedelta(hours=24)


def _contact_name(db: Session, organization_id: uuid.UUID, contact_id: uuid.UUID | None) -> str | None:
    """Never fabricates a name — returns None (callers fall back to a contact-free sentence) rather than guessing when there's no contact_id or the lookup somehow fails."""
    if contact_id is None:
        return None
    contact = ContactRepository(db).get(organization_id, contact_id)
    if contact is None:
        return None
    return f"{contact.first_name} {contact.last_name}"


def detect_overdue_tasks(db: Session, organization_id: uuid.UUID, *, now: datetime | None = None) -> list[Notification]:
    """
    One notification per overdue task, ever (see create_notification's
    dedup) — safe to call every few minutes indefinitely. Every task in
    this schema has a required assigned_to_user_id (app/schemas/task.py's
    TaskBase), so there is always a real recipient; nothing here invents
    one.
    """
    now = now or datetime.now(timezone.utc)
    overdue_tasks = TaskRepository(db).list_overdue(organization_id, now=now)

    created: list[Notification] = []
    for task in overdue_tasks:
        contact_name = _contact_name(db, organization_id, task.contact_id)
        body = f"{contact_name}: “{task.title}” is overdue (was due {task.due_at:%b %d, %Y})." if contact_name else f"“{task.title}” is overdue (was due {task.due_at:%b %d, %Y})."
        notification = create_notification(
            db,
            organization_id,
            user_id=task.assigned_to_user_id,
            notification_type="task_due",
            title="Task overdue",
            body=body,
            related_entity_type="task",
            related_entity_id=task.id,
        )
        if notification is not None:
            created.append(notification)
    return created


def detect_upcoming_appointments(
    db: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Notification]:
    """
    One notification per upcoming appointment, ever (see create_notification's
    dedup). Unlike Task, Appointment.assigned_to_user_id is optional
    (app/schemas/appointment.py) — an appointment with no assignee is
    silently skipped rather than guessing a recipient (e.g. the opportunity's
    owner), matching this whole package's "never fabricate" rule.
    """
    now = now or datetime.now(timezone.utc)
    upcoming = AppointmentRepository(db).list_upcoming(organization_id, now=now, within=UPCOMING_APPOINTMENT_WINDOW)

    created: list[Notification] = []
    for appointment in upcoming:
        if appointment.assigned_to_user_id is None:
            continue
        contact_name = _contact_name(db, organization_id, appointment.contact_id)
        # %I (not the Linux-only %-I) so this never crashes on Windows —
        # this backend's own dev environment is Windows, where %-I raises
        # ValueError; a leading zero ("05:00 PM" vs "5:00 PM") is a cosmetic
        # tradeoff worth making for that.
        when = f"{appointment.start_at:%b %d, %Y at %I:%M %p}"
        body = (
            f"{appointment.title} with {contact_name} is coming up on {when}."
            if contact_name
            else f"{appointment.title} is coming up on {when}."
        )
        notification = create_notification(
            db,
            organization_id,
            user_id=appointment.assigned_to_user_id,
            notification_type="appointment_upcoming",
            title="Upcoming appointment",
            body=body,
            related_entity_type="appointment",
            related_entity_id=appointment.id,
        )
        if notification is not None:
            created.append(notification)
    return created


def run_detectors_for_organization(
    db: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, int]:
    """Convenience entry point for app/automation/scheduler.py and tests — runs both detectors for one organization and reports how many new notifications each produced (0 on a repeat run against unchanged data, by design)."""
    overdue = detect_overdue_tasks(db, organization_id, now=now)
    upcoming = detect_upcoming_appointments(db, organization_id, now=now)
    return {"task_due": len(overdue), "appointment_upcoming": len(upcoming)}
