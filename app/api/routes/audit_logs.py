import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.audit_log import AuditLogRead
from app.schemas.user import CurrentUser
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    """"Who changed what, when" for this organization — read-only; there is no create/update/delete route, since audit_logs is only ever written by app/services/audit_service.py from inside other services."""
    return AuditService(db).list(
        current_user.organization_id, entity_type=entity_type, entity_id=entity_id, limit=limit, offset=offset
    )


@router.get("/{audit_log_id}", response_model=AuditLogRead)
def get_audit_log(
    audit_log_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
) -> AuditLogRead:
    return AuditService(db).get_or_404(current_user.organization_id, audit_log_id)
