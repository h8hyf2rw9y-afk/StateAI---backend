import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by every model — Alembic points at Base.metadata."""


class UUIDPKMixin:
    """
    Every table's primary key: a UUID generated application-side (not
    server_default=gen_random_uuid()) so a newly-constructed ORM object has
    its id available immediately, before any flush — useful for building
    related rows (e.g. a Contact and its ContactRole) in the same unit of work.
    """

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    """created_at only — for append-only/junction rows that are never meaningfully "updated" (e.g. ContactRole)."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimestampMixin(CreatedAtMixin):
    """created_at/updated_at, set by the database so they're correct regardless of caller clock skew."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
