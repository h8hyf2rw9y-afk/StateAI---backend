from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.repositories.notification_repo import NotificationRepository
from app.schemas.notification import NotificationCreate


class NotificationService:
    """
    In-app notification records — see app/models/notification.py. `create`
    is not exposed via a public route (app/api/routes/notifications.py has
    no POST): only this codebase's own services should decide a user gets
    notified, never an API client on another user's behalf. No scheduled
    job calls this yet either (see the README's Notifications Architecture
    section) — today it exists to be called directly, including from tests.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = NotificationRepository(db)

    def create(self, organization_id: uuid.UUID, data: NotificationCreate) -> Notification:
        notification = self.repo.create(organization_id, **data.model_dump())
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def list_for_user(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, *, unread_only: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        return self.repo.list_for_user(organization_id, user_id, unread_only=unread_only, limit=limit, offset=offset)

    def get_or_404_for_user(self, organization_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
        notification = self.repo.get(organization_id, notification_id)
        # Org-scoped AND owned by this specific user — a notification is
        # personal, unlike every other org-shared entity in this codebase:
        # another org member (even an owner/admin) must not read or mark
        # someone else's notification, so the ownership check happens here,
        # not just at the organization boundary.
        if notification is None or notification.user_id != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
        return notification

    def mark_read(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID, *, read: bool
    ) -> Notification:
        notification = self.get_or_404_for_user(organization_id, user_id, notification_id)
        self.repo.mark_read(notification, read=read)
        self.db.commit()
        self.db.refresh(notification)
        return notification
