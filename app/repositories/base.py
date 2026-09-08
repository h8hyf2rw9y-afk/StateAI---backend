from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class OrgScopedRepository(Generic[ModelT]):
    """
    Base CRUD for every table that carries an `organization_id` column
    (Contact, Property, BuyerRequirement, PropertyInterest). Every method
    takes `organization_id` and folds it into the WHERE clause — this is
    where tenant isolation is actually enforced, not left to callers to
    remember. See app/core/security.get_current_org_user for where that id
    comes from.
    """

    model: type[ModelT]

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, organization_id: uuid.UUID, id: uuid.UUID) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.id == id, self.model.organization_id == organization_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[ModelT]:
        stmt = (
            select(self.model)
            .where(self.model.organization_id == organization_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(self, organization_id: uuid.UUID, **fields) -> ModelT:
        obj = self.model(organization_id=organization_id, **fields)
        self.db.add(obj)
        self.db.flush()
        return obj

    def update(self, obj: ModelT, **fields) -> ModelT:
        for key, value in fields.items():
            if value is not None:
                setattr(obj, key, value)
        self.db.flush()
        return obj

    def delete(self, obj: ModelT) -> None:
        self.db.delete(obj)
        self.db.flush()