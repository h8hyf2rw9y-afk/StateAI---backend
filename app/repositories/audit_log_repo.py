from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.repositories.base import OrgScopedRepository


class AuditLogRepository(OrgScopedRepository[AuditLog]):
    """Append-only — no update()/delete() call site exists for this table on purpose; see app/services/audit_service.py."""

    model = AuditLog

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.organization_id == organization_id)
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def exists_for_entity(self, organization_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID, action: str) -> bool:
        """
        Phase 7's idempotency mechanism for the completed-appointment
        follow-up task — see app/automation/actions.py's
        create_completed_appointment_followup_task. Mirrors
        NotificationRepository.exists_for_related_entity's exact role and
        shape, applied to AuditLog instead of Notification: Task has no
        appointment_id column and no freeform related-entity pointer of its
        own (unlike Notification), so embedding a marker in a Task's own
        description would mean leaking a raw appointment UUID into text a
        real user reads — this instead reuses the audit trail every Task
        creation already produces, via the same (organization_id,
        entity_type, entity_id) index this table already has
        (ix_audit_logs_org_entity). AuditLog is not read here to *decide*
        whether an appointment needs a follow-up (that's still Appointment.status
        alone — see the detector) — only to answer "did automation already
        act on this one," the same dedup-vs-trigger distinction Phase 6
        already established for Notification.
        """
        stmt = select(AuditLog.id).where(
            AuditLog.organization_id == organization_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
            AuditLog.action == action,
        )
        return self.db.execute(stmt).first() is not None
