"""
Controlled, event-driven automation — Phase 5 (Task/Appointment
notifications), Phase 6 (Contact/BuyerRequirement/Opportunity
recommendations), Phase 7 (one controlled Level-2 write). Everything here
follows one rule, stated in each phase's brief and enforced structurally,
not just by convention: automation never gets arbitrary repository/API
access. It only ever calls one of the named functions in actions.py, each
of which is itself nothing more than a thin, already-audited, already-
organization-scoped call into an existing service (TaskService/
NotificationService/ActivityService/OpportunityService) — no new write
path exists anywhere in this package that bypasses those services.

- actions.py — the explicit, approved action layer: create_task,
  create_notification, create_activity, update_opportunity_stage (Phase 5),
  plus create_completed_appointment_followup_task (Phase 7 — the first
  action beyond Notification/Activity/an already-tested-but-unused stage
  update).
- detectors.py — read-only event detection: overdue tasks, upcoming
  appointments (Phase 5); contacts missing buyer requirements, buyer
  requirement completeness, inactive opportunities (Phase 6); completed
  appointments needing a follow-up task (Phase 7). Each is idempotent and
  safe to run any number of times.
- scheduler.py — the one piece of new infrastructure this whole package
  ever added: an in-process APScheduler job that calls every detector
  periodically. No Celery, Redis, Kafka, or separate worker process — see
  that module's own docstring for why this is the smallest option that
  fits this app's existing single-process runtime.

Level 3 (autonomous, multi-step decision-making) is explicitly not built
here — every automated action in this package is Level 2 at most (a
deterministic rule creating a low-risk, additive record) or Level 1/0 (a
detector surfacing a recommendation for a human to act on). Nothing in this
package ever calls update_opportunity_stage on its own; that action exists
in actions.py because Phase 5's brief asked for it to be an available,
tested, approved tool, but no detector or rule wires it up automatically —
moving a deal remains a human decision, made through the existing
StageSelector UI. Phase 7's create_completed_appointment_followup_task is
the one deliberate exception to "Level 2 actions are available but unused"
— see that function's own docstring for why creating a fixed-content Task
from a completed showing is safe enough to wire up automatically where
moving a deal's stage is not.
"""
