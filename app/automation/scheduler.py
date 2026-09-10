"""
The one new piece of infrastructure this phase adds. Before reaching for
it, the actual runtime was checked directly (per the phase brief's own
instruction): this backend is a single FastAPI process (`uvicorn`/
`fastapi dev`, sync SQLAlchemy, no async event loop framework already in
place, no existing job runner, no Celery/Redis/Kafka anywhere in
pyproject.toml). There is no existing periodic-work mechanism to reuse.

APScheduler's `BackgroundScheduler` was chosen specifically because it
needs none of that: it runs jobs on a plain background thread inside this
same process, using this same sync `Session` machinery — no new service to
deploy, no message broker, no separate worker. This is explicitly the
smallest option the phase brief pre-approved, not a default reached for
without checking.

Each run: iterate every organization (app/repositories/organization_repo.py's
list_all — a genuinely new capability, but a one-line addition, not new
infrastructure) and call run_detectors_for_organization with a fresh DB
session per organization, so one organization's error can't corrupt
another's transaction. Every detector is idempotent (see detectors.py) —
this can safely fire on any interval, restart at any time, or run
concurrently with a manual trigger, and never produce a duplicate.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.automation.detectors import run_detectors_for_organization
from app.core.database import SessionLocal
from app.repositories.organization_repo import OrganizationRepository

logger = logging.getLogger("app.automation.scheduler")

# How often the detectors run. A plain module constant — see detectors.py's
# UPCOMING_APPOINTMENT_WINDOW for the same "clearly documented code
# constant over a new setting" reasoning; 5 minutes is frequent enough that
# an overdue task or an upcoming appointment is never stale for long,
# without hammering the database for a demo-scale organization count.
RUN_INTERVAL_MINUTES = 5

_scheduler: BackgroundScheduler | None = None


def run_all_organizations_once() -> None:
    """
    The actual job body — also called directly by tests (with a controlled
    `now` threaded through run_detectors_for_organization, bypassed here
    since this convenience entry point always uses the real clock; tests
    call detectors.run_detectors_for_organization directly instead when
    they need a fixed time). One organization's failure is logged and
    skipped, never allowed to stop the rest — a single tenant's bad data
    must not silently stop every other tenant's notifications.
    """
    db = SessionLocal()
    try:
        organizations = OrganizationRepository(db).list_all()
    finally:
        db.close()

    for organization in organizations:
        org_db = SessionLocal()
        try:
            counts = run_detectors_for_organization(org_db, organization.id)
            if any(counts.values()):
                logger.info(
                    "automation.detectors_ran organization_id=%s task_due=%d appointment_upcoming=%d "
                    "contact_missing_requirements=%d buyer_requirement_completeness=%d opportunity_inactive=%d "
                    "completed_appointment_followup=%d",
                    organization.id,
                    counts["task_due"],
                    counts["appointment_upcoming"],
                    counts["contact_missing_requirements"],
                    counts["buyer_requirement_completeness"],
                    counts["opportunity_inactive"],
                    counts["completed_appointment_followup"],
                )
        except Exception:
            logger.exception("automation.detectors_failed organization_id=%s", organization.id)
            org_db.rollback()
        finally:
            org_db.close()


def start_scheduler() -> BackgroundScheduler:
    """Called once from app/main.py's lifespan on startup. Idempotent — calling it twice returns the same already-running scheduler rather than starting a second one."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_all_organizations_once,
        "interval",
        minutes=RUN_INTERVAL_MINUTES,
        id="automation_detectors",
        # A run that's still in flight when the next one would start is
        # skipped rather than queued — this job is idempotent (see
        # detectors.py), so there's never a correctness reason to queue
        # overlapping runs, only a resource-usage reason not to.
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("automation.scheduler_started interval_minutes=%d", RUN_INTERVAL_MINUTES)
    return scheduler


def stop_scheduler() -> None:
    """Called from app/main.py's lifespan on shutdown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
