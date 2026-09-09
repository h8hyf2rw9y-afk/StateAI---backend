from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.notification import Notification
from app.repositories.base import OrgScopedRepository


class NotificationRepository(OrgScopedRepository[Notification]):
    model = Notification

    def list_for_user(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        stmt = select(Notification).where(
            Notification.organization_id == organization_id, Notification.user_id == user_id
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def mark_read(self, notification: Notification, *, read: bool) -> Notification:
        notification.read_at = datetime.now(timezone.utc) if read else None
        self.db.flush()
        return notification
