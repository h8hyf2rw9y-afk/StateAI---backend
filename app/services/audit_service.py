from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.repositories.audit_log_repo import AuditLogRepository


class AuditService:
    """
    The one reusable place that writes to `audit_logs` (app/models/audit_log.py).
    A Service method calls `.record(...)` around its own existing create/update/
    delete — never a route directly, and never duplicated ad hoc per module —
    so every future entity (Task, Appointment, ...) logs the same shape the
    same way just by composing this class, exactly like every other shared
    repository/service in this codebase.

    Deliberately does not call db.commit(): the caller's own existing commit
    already covers the audit row in the same unit of work as the change it
    describes, so the log entry and the change it records either both
    persist or both roll back together.

    organization_id/actor_user_id must always be the caller's own
    CurrentUser fields, never anything read from request body — see every
    call site in app/services/*.py.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AuditLogRepository(db)

    def record(
        self,
        *,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        before: dict | None = None,
        after: dict | None = None,
    ) -> AuditLog:
        return self.repo.create(
            organization_id,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before_data=before,
            after_data=after,
        )

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        return self.repo.list(organization_id, entity_type=entity_type, entity_id=entity_id, limit=limit, offset=offset)

    def get_or_404(self, organization_id: uuid.UUID, audit_log_id: uuid.UUID) -> AuditLog:
        log = self.repo.get(organization_id, audit_log_id)
        if log is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit log not found.")
        return log
