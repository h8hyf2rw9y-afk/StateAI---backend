"""
The explicit, approved action layer — see app/automation/__init__.py for
the rule this whole package exists to enforce. Every function here takes
`organization_id` explicitly (never infers it), validates its inputs
through the same service every human-triggered write already goes through,
and leaves an audit trail. A detector or rule may only ever call one of
these four functions — never a repository, never a service method not
wrapped here, never a raw SQL statement.

None of these four functions know anything about *why* they're being
called — that's the detector's or rule's job (app/automation/detectors.py).
This module is purely "given a fully-decided, validated action, carry it
out safely and auditably."
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.notification import Notification
from app.models.opportunity import Opportunity
from app.models.task import Task
from app.repositories.notification_repo import NotificationRepository
from app.schemas.activity import ActivityCreate
from app.schemas.opportunity import OpportunityUpdate
from app.schemas.task import TaskCreate
from app.services.activity_service import ActivityService
from app.services.audit_service import AuditService
from app.services.task_service import TaskService


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
