"""
Controlled, event-driven automation — Phase 5. Everything here follows one
rule, stated in the phase brief and enforced structurally, not just by
convention: automation never gets arbitrary repository/API access. It only
ever calls one of the four named functions in actions.py, each of which is
itself nothing more than a thin, already-audited, already-organization-
scoped call into an existing service (TaskService/NotificationService/
ActivityService/OpportunityService) — no new write path exists anywhere in
this package that bypasses those services.

- actions.py — the explicit, approved action layer (create_task,
  create_notification, create_activity, update_opportunity_stage).
- detectors.py — read-only event detection (overdue tasks, upcoming
  appointments), each idempotent and safe to run any number of times.
- scheduler.py — the one piece of new infrastructure this phase adds: an
  in-process APScheduler job that calls the detectors periodically. No
  Celery, Redis, Kafka, or separate worker process — see that module's own
  docstring for why this is the smallest option that fits this app's
  existing single-process runtime.

Level 3 (autonomous, multi-step decision-making) is explicitly not built
here — every automated action in this package is Level 2 at most (a
deterministic rule creating a low-risk, additive record) or Level 1 (a
detector surfacing a recommendation for a human to act on). Nothing in this
package ever calls update_opportunity_stage on its own; that action exists
in actions.py because the phase brief asks for it to be an available,
tested, approved tool, but no detector or rule wires it up automatically —
moving a deal remains a human decision, made through the existing
StageSelector UI, in this phase.
"""
