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
