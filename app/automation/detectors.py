"""
Event detection — the DETECT step of EVENT -> DETECT -> CONTEXT -> RULE ->
ACTION -> AUDIT -> NOTIFICATION. Every detector here is a plain, read-only,
deterministic query: no LLM call and no CONTEXT/RULE step beyond a direct
comparison against already-stored CRM fields — see the phase brief's own
instruction not to turn a deterministic event into an unnecessary AI call.
The Lead Intelligence, Follow-up, and Pipeline Agents already exist for the
actual "what should the advisor do about it" question; these detectors
only decide *whether to notify*, not what to recommend — a notification
body may point at the relevant agent/panel, but never calls it.

Every detector takes `organization_id` explicitly and only ever queries
within it, takes `now` as an explicit parameter (never computing it
internally) so tests can pass a fixed, controlled time, and only ever
writes through one of app/automation/actions.py's functions — each of
which owns its own idempotency check internally (create_notification via
Notification dedup; create_completed_appointment_followup_task via
AuditLog dedup — see each one's own docstring). Running any detector any
number of times, at any interval, for the same organization can never
create more than one notification or task per underlying event.

Phase 6, Part 4 / Phase 7, Part 18: every detector in this file reads only
real CRM tables (Contact, BuyerRequirement, Opportunity, Task, Appointment)
— never Notification, never AuditLog, as its *business trigger* (whether
an event is happening at all). This is what makes an event -> AI -> action
-> event feedback loop structurally impossible here: nothing in this
module's own inputs is something this module (or the action layer it
calls) ever writes as CRM state. The one narrow exception — Phase 7's
create_completed_appointment_followup_task reading AuditLog purely to
check "did automation already handle this appointment" — is a dedup
*safety layer*, not a trigger, the same distinction Notification's own
dedup already established; see that function's docstring.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.automation.actions import create_completed_appointment_followup_task, create_notification
from app.models.notification import Notification
from app.models.task import Task
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.buyer_requirement_repo import BuyerRequirementRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.opportunity_repo import OpportunityRepository
from app.repositories.organization_repo import UserRepository
from app.repositories.task_repo import TaskRepository

logger = logging.getLogger("app.automation.detectors")

# How far ahead "upcoming" looks for an appointment reminder. A plain
# module constant, not a new environment variable — see the phase brief's
# "configurable or clearly documented" allowance and app/core/config.py's
# own precedent of keeping single-purpose tuning knobs as code constants
# until a real reason to vary them per-deployment shows up.
UPCOMING_APPOINTMENT_WINDOW = timedelta(hours=24)

# Phase 6 — how long an open (non-closed) opportunity can go without any
# update before it's flagged as inactive. Same "plain, documented constant"
# reasoning as UPCOMING_APPOINTMENT_WINDOW above, not a new setting.
OPPORTUNITY_INACTIVITY_THRESHOLD = timedelta(days=10)


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite (unlike Postgres) drops tzinfo on round-trip even for a DateTime(timezone=True) column — subtracting/comparing an aware `now` against a naive value read back in tests would raise TypeError. Same quirk app/services/lead_context_service.py and app/services/appointment_service.py already work around."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


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


def _notify_every_org_user(
    db: Session,
    organization_id: uuid.UUID,
    *,
    notification_type: str,
    title: str,
    body: str,
    related_entity_type: str,
    related_entity_id: uuid.UUID,
) -> list[Notification]:
    """
    Contact and BuyerRequirement have no owner/assignee column (unlike
    Task/Appointment/Opportunity) — see UserRepository.list_for_organization's
    own docstring for why "every user in this organization" is the correct,
    non-fabricated recipient set here rather than inventing one. Each
    user's notification is still its own independently deduplicated row.
    """
    created: list[Notification] = []
    for user in UserRepository(db).list_for_organization(organization_id):
        notification = create_notification(
            db,
            organization_id,
            user_id=user.id,
            notification_type=notification_type,
            title=title,
            body=body,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        if notification is not None:
            created.append(notification)
    return created


def detect_contacts_missing_requirements(
    db: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Notification]:
    """
    Phase 6, Example A: a Contact with zero BuyerRequirement rows (any
    status — see ContactRepository.list_without_buyer_requirements) is a
    lead nobody has started qualifying yet. `now` is accepted for the same
    explicit-clock convention every detector in this module follows, even
    though this particular check has no time-based condition of its own.
    Points the notification at the contact's own detail page
    (related_entity_type="contact") — see features/notifications/types.ts's
    getNotificationLink, which is where every Phase 6 recommendation about
    a contact or its buyer requirement ends up, since that's the one real
    page (`/leads/{id}`) where both live in this app.
    """
    del now  # unused — kept for signature consistency with the other detectors
    contacts = ContactRepository(db).list_without_buyer_requirements(organization_id)

    created: list[Notification] = []
    for contact in contacts:
        contact_name = f"{contact.first_name} {contact.last_name}"
        body = (
            f"{contact_name} doesn't have buyer requirements yet. Add their budget, "
            "location, and property preferences so STATE AI can search for matching properties."
        )
        created.extend(
            _notify_every_org_user(
                db,
                organization_id,
                notification_type="contact_missing_requirements",
                title="Missing buyer requirements",
                body=body,
                related_entity_type="contact",
                related_entity_id=contact.id,
            )
        )
    return created


def _missing_requirement_fields(requirement) -> list[str]:
    """
    Phase 6, Example B — deterministic completeness, not an LLM judgment.
    Reuses the exact three criteria app/services/matching_service.py's
    MatchingService.find_matches already treats as its real narrowing
    filters (property_type, budget_min/max, locations) — the smallest
    defensible "ready for matching" definition, because it's the one
    already encoded in how matching actually works, not invented fresh
    for this detector. Bedrooms/bathrooms/features etc. are optional
    refinements in that same method (only applied `if` present), so they
    are not required here either.
    """
    missing = []
    if not requirement.property_type:
        missing.append("property type")
    if requirement.budget_min is None and requirement.budget_max is None:
        missing.append("budget")
    if not requirement.locations:
        missing.append("location")
    return missing


def detect_incomplete_buyer_requirements(
    db: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Notification]:
    """
    Phase 6, Example B: every *active* BuyerRequirement (paused/fulfilled/
    cancelled ones are no longer being actively worked toward matching —
    see BuyerRequirementRepository.list_active) is evaluated against
    _missing_requirement_fields. An incomplete one gets a notification
    naming exactly what's missing; a complete one gets a distinctly-typed
    "ready for matching" notification instead — different `type` values
    (see app/schemas/enums.py's NotificationType), so a requirement that
    starts incomplete and later becomes complete gets both notifications
    over its lifetime (each deduplicated independently), never a duplicate
    of either. Deduplicated per requirement_id, not per contact_id: a
    contact can have more than one BuyerRequirement over time (an old
    cancelled search plus a new active one is an existing, real pattern in
    this schema — app/models/buyer_requirement.py's own docstring), and
    each one's completeness is its own event.
    """
    del now  # unused — kept for signature consistency with the other detectors
    requirements = BuyerRequirementRepository(db).list_active(organization_id)

    created: list[Notification] = []
    for requirement in requirements:
        contact_name = _contact_name(db, organization_id, requirement.contact_id) or "This client"
        missing = _missing_requirement_fields(requirement)

        if missing:
            notification_type = "buyer_requirement_incomplete"
            title = "Buyer requirement needs more information"
            body = f"{contact_name}'s buyer requirement is missing: {', '.join(missing)}."
        else:
            notification_type = "buyer_requirement_ready"
            title = "Ready for property matching"
            body = (
                f"{contact_name}'s buyer requirement now has enough detail "
                "(budget, property type, and location) — run Buyer Matching to find properties."
            )

        created.extend(
            _notify_every_org_user(
                db,
                organization_id,
                notification_type=notification_type,
                title=title,
                body=body,
                related_entity_type="buyer_requirement",
                related_entity_id=requirement.id,
            )
        )
    return created


def detect_inactive_opportunities(
    db: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Notification]:
    """
    Phase 6, Example E: an open (non-closed) Opportunity whose `updated_at`
    is older than OPPORTUNITY_INACTIVITY_THRESHOLD — see
    OpportunityRepository.list_inactive. Recipient falls back from
    owner_user_id to created_by_user_id, the exact same fallback
    OpportunityService._maybe_create_post_sale_task already uses for this
    entity; if neither is known, this opportunity is skipped (logged, not
    raised — never fabricate a recipient). The notification names the
    Pipeline Agent explicitly — see the phase brief's Example E and Part 9
    (Automation Detector -> Notification -> human opens it -> existing
    Pipeline Agent), never invoking it itself.
    """
    now = now or datetime.now(timezone.utc)
    inactive = OpportunityRepository(db).list_inactive(
        organization_id, now=now, since=OPPORTUNITY_INACTIVITY_THRESHOLD
    )

    created: list[Notification] = []
    for opportunity in inactive:
        assignee = opportunity.owner_user_id or opportunity.created_by_user_id
        if assignee is None:
            logger.warning(
                "automation.inactive_opportunity_skipped opportunity_id=%s reason=no_assignee", opportunity.id
            )
            continue

        contact_name = _contact_name(db, organization_id, opportunity.contact_id) or "the client"
        days_inactive = (now - _as_aware_utc(opportunity.updated_at)).days
        body = (
            f"{contact_name}'s opportunity \"{opportunity.title}\" has had no updates in "
            f"{days_inactive} days. Review it and consider a follow-up — the Pipeline Agent "
            "can help decide the next step."
        )
        notification = create_notification(
            db,
            organization_id,
            user_id=assignee,
            notification_type="opportunity_inactive",
            title="Opportunity inactive",
            body=body,
            related_entity_type="opportunity",
            related_entity_id=opportunity.id,
        )
        if notification is not None:
            created.append(notification)
    return created


def detect_completed_appointments_needing_followup(
    db: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Task]:
    """
    Phase 7 — the project's first Level-2 (controlled automation) detector:
    unlike every detector above, this one's action creates a Task, not a
    Notification. The business rule is exactly the one the phase brief
    specifies and nothing more: `appointment.status == "completed"` (real
    CRM state — see AppointmentRepository.list_completed) AND "no follow-up
    task already exists for it" (checked inside
    create_completed_appointment_followup_task via AuditLog — never via
    Notification or this module reading its own prior output, preserving
    the same no-feedback-loop invariant every detector in this file
    follows). `now` is accepted for the same explicit-clock signature
    convention as every other detector, even though this rule has no
    time-based condition of its own — completion, not elapsed time, is
    what triggers it.
    """
    del now  # unused — kept for signature consistency with the other detectors
    completed = AppointmentRepository(db).list_completed(organization_id)

    created: list[Task] = []
    for appointment in completed:
        task = create_completed_appointment_followup_task(db, organization_id, appointment=appointment)
        if task is not None:
            created.append(task)
    return created


def run_detectors_for_organization(
    db: Session, organization_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, int]:
    """Convenience entry point for app/automation/scheduler.py and tests — runs every detector for one organization and reports how many new notifications/tasks each produced (0 on a repeat run against unchanged data, by design)."""
    overdue = detect_overdue_tasks(db, organization_id, now=now)
    upcoming = detect_upcoming_appointments(db, organization_id, now=now)
    missing_requirements = detect_contacts_missing_requirements(db, organization_id, now=now)
    requirement_completeness = detect_incomplete_buyer_requirements(db, organization_id, now=now)
    inactive_opportunities = detect_inactive_opportunities(db, organization_id, now=now)
    completed_appointment_followups = detect_completed_appointments_needing_followup(db, organization_id, now=now)
    return {
        "task_due": len(overdue),
        "appointment_upcoming": len(upcoming),
        "contact_missing_requirements": len(missing_requirements),
        "buyer_requirement_completeness": len(requirement_completeness),
        "opportunity_inactive": len(inactive_opportunities),
        "completed_appointment_followup": len(completed_appointment_followups),
    }
