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

    def exists_for_related_entity(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_type: str,
        related_entity_type: str,
        related_entity_id: uuid.UUID,
    ) -> bool:
        """
        The entire deduplication strategy for event-driven notifications
        (see app/automation/actions.py's create_notification and the
        detectors in app/automation/detectors.py): one (user, type,
        related_entity) triple ever gets a notification, period — not "one
        per day" or "one per detector run." A task that's been overdue for
        a week and gets checked every 5 minutes must produce exactly one
        notification, not hundreds; this is checked before every automated
        create_notification call, so running a detector any number of
        times, however often, can never create a duplicate. Deliberately
        does not consider read_at: even a notification the user already
        read and dismissed must not be recreated just because the same
        task is still overdue tomorrow — the user was already told once.
        """
        stmt = select(Notification.id).where(
            Notification.organization_id == organization_id,
            Notification.user_id == user_id,
            Notification.type == notification_type,
            Notification.related_entity_type == related_entity_type,
            Notification.related_entity_id == related_entity_id,
        )
        return self.db.execute(stmt).first() is not None
