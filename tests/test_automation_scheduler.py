"""
app/automation/scheduler.py's job body — the detectors' own idempotency is
already exhaustively covered in tests/test_automation_detectors.py; this
file only covers the scheduler-specific behavior layered on top: iterating
every real organization, and one organization's failure never stopping
another's.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.automation.scheduler import run_all_organizations_once
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.task import Task


def test_runs_detectors_for_a_real_organization(db_session: Session, organization_id, current_user):
    task = Task(
        organization_id=organization_id,
        assigned_to_user_id=current_user.id,
        title="Overdue task",
        task_type="follow_up",
        status="pending",
        due_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(task)
    db_session.commit()

    # run_all_organizations_once opens its own sessions via SessionLocal
    # (app/core/database.py), not the test's in-memory db_session fixture —
    # patched to the same in-memory engine so this exercises the real
    # iterate-every-organization code path against real, already-seeded
    # test data instead of a second, disconnected database.
    with patch("app.automation.scheduler.SessionLocal", lambda: db_session):
        with patch.object(db_session, "close", lambda: None):  # keep the fixture's session alive across "closes"
            run_all_organizations_once()

    notifications = db_session.query(Notification).filter(Notification.type == "task_due").all()
    assert len(notifications) == 1
    assert notifications[0].related_entity_id == task.id


def test_one_organizations_failure_does_not_stop_another(db_session: Session, organization_id, current_user):
    """A bad organization's detector run is logged and skipped, never allowed to take every other tenant's run down with it."""
    other_org = Organization(name="Broken Org")
    db_session.add(other_org)
    db_session.commit()

    call_count = {"n": 0}
    real_run = None

    def flaky_run(db, org_id, **kwargs):
        call_count["n"] += 1
        if org_id == other_org.id:
            raise RuntimeError("simulated failure")
        return real_run(db, org_id, **kwargs)

    from app.automation import detectors

    real_run = detectors.run_detectors_for_organization

    with patch("app.automation.scheduler.SessionLocal", lambda: db_session):
        with patch.object(db_session, "close", lambda: None):
            with patch("app.automation.scheduler.run_detectors_for_organization", side_effect=flaky_run):
                run_all_organizations_once()  # must not raise

    assert call_count["n"] == 2  # both organizations were attempted
