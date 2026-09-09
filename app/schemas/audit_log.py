import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class AuditLogRead(ORMModel):
    """Read-only by design — audit_logs has no Create/Update schema because clients never write to it directly; see app/services/audit_service.py."""

    id: uuid.UUID
    organization_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID
    action: str
    before_data: dict | None
    after_data: dict | None
    created_at: datetime
