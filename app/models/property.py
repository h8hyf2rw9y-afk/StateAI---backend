import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Property(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "properties"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(nullable=False)
    # Soft enums (app/schemas/enums.py): property_type, status.
    property_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="draft")

    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(nullable=False, default="MXN")

    address_line: Mapped[str | None] = mapped_column(nullable=True)
    city: Mapped[str | None] = mapped_column(nullable=True)
    state: Mapped[str | None] = mapped_column(nullable=True)
    postal_code: Mapped[str | None] = mapped_column(nullable=True)
    neighborhood: Mapped[str | None] = mapped_column(nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    construction_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    land_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)  # half-baths are common
    parking_spaces: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    description: Mapped[str | None] = mapped_column(nullable=True)

    features: Mapped[list["PropertyFeature"]] = relationship(back_populates="property", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_properties_organization_id", "organization_id"),
        Index("ix_properties_org_status_city_type", "organization_id", "status", "city", "property_type"),
        Index("ix_properties_price", "price"),
    )


class PropertyFeature(Base, UUIDPKMixin):
    """What a property actually has — matched against buyer_requirement_features' must_have entries."""

    __tablename__ = "property_features"

    property_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    feature_key: Mapped[str] = mapped_column(ForeignKey("features.key"), nullable=False)

    property: Mapped["Property"] = relationship(back_populates="features")
    feature = relationship("Feature")

    __table_args__ = (UniqueConstraint("property_id", "feature_key", name="uq_property_features_property_feature"),)
