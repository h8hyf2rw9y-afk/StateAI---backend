"""
The explicit, approved action layer — see app/automation/__init__.py for
the rule this whole package exists to enforce. Every function here takes
`organization_id` explicitly (never infers it), validates its inputs
through the same service every human-triggered write already goes through,
and leaves an audit trail. A detector or rule may only ever call one of
these functions — never a repository, never a service method not wrapped
here, never a raw SQL statement.

None of these functions know anything about *why* they're being called —
that's the detector's or rule's job (app/automation/detectors.py). This
module is purely "given a fully-decided, validated action, carry it out
safely and auditably."

Phase 7 adds one new function, create_completed_appointment_followup_task
— the project's first Level-2 action (a controlled, deterministic CRM
*write* beyond a Notification): see that function's own docstring for its
idempotency design.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.appointment import Appointment
from app.models.notification import Notification
from app.models.opportunity import Opportunity
from app.models.task import Task
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.notification_repo import NotificationRepository
from app.repositories.opportunity_repo import OpportunityRepository
from app.schemas.activity import ActivityCreate
from app.schemas.opportunity import OpportunityUpdate
from app.schemas.task import TaskCreate
from app.services.activity_service import ActivityService
from app.services.audit_service import AuditService
from app.services.task_service import TaskService

logger = logging.getLogger("app.automation.actions")


def create_task(
    db: Session,
    organization_id: uuid.UUID,
    *,
    assigned_to_user_id: uuid.UUID,
    title: str,
    task_type: str,
    due_at: datetime,
    priority: str = "medium",
    description: str | None = None,
    contact_id: uuid.UUID | None = None,
    property_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Task:
    """
    `actor_user_id=None` means "the system created this, not a person" —
    the same nullable-actor convention every AuditLog entry in this
    codebase already uses (see app/models/audit_log.py); this is not a new
    concept introduced for automation. TaskService.create already validates
    every reference (contact/property/opportunity must resolve in this
    organization) and records its own TASK_CREATED audit entry — this
    wrapper adds nothing beyond calling it with the right shape, which is
    the whole point: no new write path, just a named, approved entry point.
    """
    data = TaskCreate(
        assigned_to_user_id=assigned_to_user_id,
        contact_id=contact_id,
        property_id=property_id,
        opportunity_id=opportunity_id,
        title=title,
        description=description,
        task_type=task_type,
        priority=priority,
        due_at=due_at,
    )
    return TaskService(db).create(organization_id, data, actor_user_id)


def create_activity(
    db: Session,
    organization_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    activity_type: str,
    notes: str,
    occurred_at: datetime,
    direction: str | None = None,
    property_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Activity:
    """Same reasoning as create_task above — ActivityService.create already validates references and records its own ACTIVITY_CREATED audit entry."""
    data = ActivityCreate(
        activity_type=activity_type,
        direction=direction,
        property_id=property_id,
        opportunity_id=opportunity_id,
        occurred_at=occurred_at,
        notes=notes,
    )
    return ActivityService(db).create(organization_id, contact_id, actor_user_id, data)


def update_opportunity_stage(
    db: Session,
    organization_id: uuid.UUID,
    *,
    opportunity_id: uuid.UUID,
    stage: str,
    lost_reason: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Opportunity:
    """
    Exposed as an approved tool — per the phase brief — but not called by
    any detector or rule in this phase; moving a deal's stage remains a
    human action through the existing StageSelector UI
    (features/pipeline/components/stage-selector.tsx) and its real
    PATCH /opportunities/{id} endpoint. This function exists so the tool is
    already built, tested, and ready for a future phase to wire up
    deliberately, rather than being invented under time pressure then.

    Local import, not a module-level one: app/services/opportunity_service.py
    imports create_task from this module (for the post-sale follow-up task
    — see its own docstring) — a module-level import of OpportunityService
    here would make the two modules import each other at load time. Since
    this function is only ever *called* well after both modules have
    already finished loading, a local import breaks the cycle with no
    behavior change.
    """
    from app.services.opportunity_service import OpportunityService

    data = OpportunityUpdate(stage=stage, lost_reason=lost_reason)
    return OpportunityService(db).update(organization_id, opportunity_id, data, actor_user_id)


def create_notification(
    db: Session,
    organization_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
) -> Notification | None:
    """
    The one action wrapper with real logic of its own, not just a pass-
    through: deduplication. See NotificationRepository.exists_for_related_entity
    for the exact strategy — this is what makes it safe for
    app/automation/scheduler.py to run the detectors any number of times
    without ever creating a duplicate notification for the same underlying
    event. Returns None (a no-op, not an error) when a matching notification
    already exists — "already notified" is a normal, expected outcome here,
    not a failure.

    Audited explicitly, unlike NotificationService.create itself (which has
    no caller today besides tests and this wrapper — see its own docstring):
    every notification in this phase is automation-created, so recording
    *why* one appeared (which organization, which related entity, which
    detector) matters more here than it would for a hypothetical future
    human-triggered notification.

    Deliberately calls NotificationRepository directly rather than
    NotificationService.create: that service method is a bare
    repo.create-then-commit with no validation of its own to preserve (read
    its own source — there's nothing there beyond the repo call), and
    calling it here would commit the notification in its own transaction
    before the audit entry below exists, same failure-window problem every
    other *Service.create method in this codebase avoids by doing exactly
    one commit after both the row and its audit entry are staged. This
    keeps that same one-commit guarantee rather than introducing a new,
    weaker two-commit pattern just for this one wrapper.
    """
    repo = NotificationRepository(db)
    if related_entity_type is not None and related_entity_id is not None:
        if repo.exists_for_related_entity(organization_id, user_id, notification_type, related_entity_type, related_entity_id):
            return None

    notification = repo.create(
        organization_id,
        user_id=user_id,
        type=notification_type,
        title=title,
        body=body,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    AuditService(db).record(
        organization_id=organization_id,
        actor_user_id=None,
        entity_type="notification",
        entity_id=notification.id,
        action="NOTIFICATION_CREATED",
        after={
            "type": notification_type,
            "title": title,
            "related_entity_type": related_entity_type,
            "related_entity_id": str(related_entity_id) if related_entity_id else None,
        },
    )
    db.commit()
    db.refresh(notification)
    return notification


# Phase 7, Part 12 — "due_at = appointment completion timestamp + 1 day" per
# the phase brief's own preferred fallback rule. Appointment has no
# completed_at column (unlike Task, which does) — see app/models/appointment.py
# — so `updated_at` (TimestampMixin, bumped on every write, including the
# PATCH that sets status="completed") is the safest existing timestamp to
# treat as "when this was completed," same reasoning already applied to
# app/automation/detectors.py's OPPORTUNITY_INACTIVITY_THRESHOLD.
COMPLETED_SHOWING_FOLLOWUP_DAYS = 1

# A distinct AuditLog `action` value, recorded against the *appointment*
# (entity_type="appointment", entity_id=appointment.id) — not the task —
# purely so create_completed_appointment_followup_task can ask "did
# automation already act on this appointment" without touching Notification
# or Task. See AuditLogRepository.exists_for_entity's own docstring for why
# this, and not a marker embedded in the Task's own description, is the
# idempotency mechanism here.
_FOLLOWUP_TASK_AUDIT_ACTION = "APPOINTMENT_FOLLOWUP_TASK_CREATED"


def _as_aware_utc(value: datetime) -> datetime:
    """Same SQLite-drops-tzinfo-on-round-trip workaround as app/automation/detectors.py and app/services/appointment_service.py — needed here since `appointment.updated_at` comes straight off the ORM object."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def create_completed_appointment_followup_task(
    db: Session, organization_id: uuid.UUID, *, appointment: Appointment
) -> Task | None:
    """
    Phase 7's one new Level-2 action: a completed showing/appointment gets
    exactly one fixed-content follow-up Task, created automatically. This
    is deliberately the *only* new autonomous CRM write this phase adds —
    everything else in the DETECT -> DETERMINE -> RECOMMEND chain still
    only ever produces a Notification (see app/automation/detectors.py's
    own module docstring for the full boundary).

    Idempotency: checked via AuditLogRepository.exists_for_entity BEFORE
    doing anything else, keyed on (organization_id, "appointment",
    appointment.id, _FOLLOWUP_TASK_AUDIT_ACTION) — an appointment that
    already produced its follow-up task is a silent no-op (returns None),
    exactly like create_notification's own dedup contract above. The
    marker audit row is staged (AuditService.record — flush only, no
    commit of its own; see that method's docstring) *before* calling
    create_task below, so it rides inside create_task's own eventual
    commit (via TaskService.create) as one atomic unit: either both the
    Task and its "already handled" marker persist together, or neither
    does. Recording the marker only *after* create_task returned would
    instead need a second, separate commit — reopening exactly the
    crash-between-two-commits gap this ordering avoids.

    Ownership: appointment.assigned_to_user_id first (an appointment
    already has a real, direct assignee in the vast majority of cases —
    the real AppointmentForm defaults it to the signed-in user). Falling
    back to the linked Opportunity's owner_user_id when the appointment
    itself has no assignee — the same two-candidate fallback chain
    app/services/opportunity_service.py's _maybe_create_post_sale_task
    already established for this exact problem (Phase 5). Contact has no
    owner/assignee column at all in this schema (confirmed by inspection —
    see app/models/contact.py), so there is no third fallback to reuse; if
    neither candidate resolves to a real user, this is skipped (logged,
    not raised) rather than fabricating a recipient — never itself a
    reason to block anything else in the automation cycle.

    A task with no real contact_id is skipped, never created — Appointment.
    contact_id is nullable (a non-showing appointment, e.g. a plain
    "call", may have none), and a follow-up task about nobody specific
    isn't useful CRM data (mirrors this whole package's established
    "never fabricate" rule).
    """
    if appointment.contact_id is None:
        return None

    audit_repo = AuditLogRepository(db)
    if audit_repo.exists_for_entity(organization_id, "appointment", appointment.id, _FOLLOWUP_TASK_AUDIT_ACTION):
        return None

    assignee = appointment.assigned_to_user_id
    if assignee is None and appointment.opportunity_id is not None:
        opportunity = OpportunityRepository(db).get(organization_id, appointment.opportunity_id)
        if opportunity is not None:
            assignee = opportunity.owner_user_id
    if assignee is None:
        logger.warning(
            "automation.completed_appointment_followup_skipped appointment_id=%s reason=no_assignee",
            appointment.id,
        )
        return None

    AuditService(db).record(
        organization_id=organization_id,
        actor_user_id=None,
        entity_type="appointment",
        entity_id=appointment.id,
        action=_FOLLOWUP_TASK_AUDIT_ACTION,
        after={"task_type": "follow_up", "trigger": "appointment_completed"},
    )

    due_at = _as_aware_utc(appointment.updated_at) + timedelta(days=COMPLETED_SHOWING_FOLLOWUP_DAYS)

    task = create_task(
        db,
        organization_id,
        assigned_to_user_id=assignee,
        title="Review completed showing outcome and follow up with client",
        description=(
            "Review the outcome of the completed showing and determine the appropriate next follow-up with the client."
        ),
        task_type="follow_up",
        due_at=due_at,
        contact_id=appointment.contact_id,
        property_id=appointment.property_id,
        opportunity_id=appointment.opportunity_id,
        actor_user_id=None,
    )

    # Section 16 of the phase brief: decide whether a Notification is
    # redundant with the Task UI, rather than adding one by default. It is
    # NOT redundant here — a Task that appears in the Tasks list is
    # something the agent has to go looking for, exactly the "agent
    # remembers to check" pattern this whole product is moving away from
    # (see the module docstring's Phase 6/7 distinction). The bell is
    # already the one established "what did STATE AI just do" surface
    # (Phase 6); skipping it here would make this the one automation path
    # with no proactive signal at all. Reuses create_notification as-is —
    # same dedup, same audit trail, same contract — with
    # related_entity_type="task" so the existing frontend
    # getNotificationLink "task" case (-> /tasks) already works with zero
    # frontend changes.
    # Known, accepted gap (same category as any two-commit sequence in this
    # codebase): create_task above already committed by the time we reach
    # here, so this notification is a second, separate commit — if the
    # process crashed in between, the Task would exist with no
    # notification, and the next run's idempotency check (keyed on the
    # appointment, not the notification) would skip re-attempting it. Not
    # solved here as it would require restructuring create_task's own
    # commit boundary for a single-process demo-scale app; flagged rather
    # than silently accepted.
    contact = ContactRepository(db).get(organization_id, appointment.contact_id)
    contact_name = f"{contact.first_name} {contact.last_name}" if contact else "the client"
    create_notification(
        db,
        organization_id,
        user_id=assignee,
        notification_type="followup_task_created",
        title="Follow-up task created",
        body=(
            f"A follow-up task was created for the completed showing with {contact_name}. "
            "Review the showing outcome and follow up with the client."
        ),
        related_entity_type="task",
        related_entity_id=task.id,
    )

    return task
