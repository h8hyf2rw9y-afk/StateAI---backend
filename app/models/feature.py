from sqlalchemy import Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Feature(Base, TimestampMixin):
    """
    Catalog shared by both buyer_requirement_features and property_features
    (e.g. "pool", "garden", "home_office") — one place to add a new
    feature, no migration, no hardcoded boolean columns.

    `key` (not a UUID) stays the primary key: it's the same natural-key
    catalog pattern already used by Role (app/models/contact.py), and both
    property_features.feature_key and buyer_requirement_features.feature_key
    already reference it directly. Introducing a separate UUID `id` would
    duplicate identity for no benefit and would ripple into those two
    tables' foreign keys — exactly the kind of unnecessary redesign this
    catalog is meant to avoid (see GET /features in app/api/routes/features.py).
    """

    __tablename__ = "features"

    key: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
    # Soft enum (app/schemas/enums.py): category.
    category: Mapped[str | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
