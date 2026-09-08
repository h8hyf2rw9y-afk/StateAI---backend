from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.repositories.activity_repo import ActivityRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.property_repo import PropertyRepository
from app.schemas.activity import ActivityCreate


class ActivityService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ActivityRepository(db)
        self.contact_repo = ContactRepository(db)
        self.property_repo = PropertyRepository(db)

    def get_or_404(self, organization_id: uuid.UUID, activity_id: uuid.UUID) -> Activity:
        activity = self.repo.get(organization_id, activity_id)
        if activity is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found.")
        return activity

    def create(
        self,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        created_by_user_id: uuid.UUID | None,
        data: ActivityCreate,
    ) -> Activity:
        if self.contact_repo.get(organization_id, contact_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        if data.property_id is not None and self.property_repo.get(organization_id, data.property_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")

        activity = self.repo.create(
            organization_id,
            contact_id=contact_id,
            created_by_user_id=created_by_user_id,
            **data.model_dump(),
        )
        self.db.commit()
        self.db.refresh(activity)
        return activity

    def list_for_contact(
        self,
        organization_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        activity_type: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> list[Activity]:
        if self.contact_repo.get(organization_id, contact_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        return self.repo.list_for_contact(
            organization_id, contact_id, activity_type=activity_type, occurred_from=occurred_from, occurred_to=occurred_to
        )

    def list_for_property(
        self,
        organization_id: uuid.UUID,
        property_id: uuid.UUID,
        *,
        activity_type: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> list[Activity]:
        if self.property_repo.get(organization_id, property_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")
        return self.repo.list_for_property(
            organization_id, property_id, activity_type=activity_type, occurred_from=occurred_from, occurred_to=occurred_to
        )
