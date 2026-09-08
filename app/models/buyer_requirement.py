import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPKMixin


def _minmax_check(field: str, name: str) -> CheckConstraint:
    """`col_min <= col_max`, but only when both are present — NULL means "no bound", not "invalid"."""
    return CheckConstraint(
        f"{field}_min IS NULL OR {field}_max IS NULL OR {field}_min <= {field}_max",
        name=name,
    )


class BuyerRequirement(Base, UUIDPKMixin, TimestampMixin):
    """
    "I'm looking for properties matching THESE criteria" — as opposed to a
    PropertyInterest, which is "I'm interested in THIS specific property".
    A Contact can have several of these over time (see the plan's Case B).
    """

    __tablename__ = "buyer_requirements"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )

    # Soft enums (app/schemas/enums.py): purpose, status, property_type, timeline, financing_type, preapproval_status.
    purpose: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="active")

    budget_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    budget_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(nullable=False, default="MXN")

    property_type: Mapped[str | None] = mapped_column(nullable=True)

    bedrooms_min: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bedrooms_max: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bathrooms_min: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    bathrooms_max: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    construction_m2_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    construction_m2_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    land_m2_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    land_m2_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    parking_spaces_min: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    timeline: Mapped[str | None] = mapped_column(nullable=True)
    financing_type: Mapped[str | None] = mapped_column(nullable=True)
    preapproval_status: Mapped[str | None] = mapped_column(nullable=True)

    motivation: Mapped[str | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)

    locations: Mapped[list["BuyerRequirementLocation"]] = relationship(
        back_populates="buyer_requirement", cascade="all, delete-orphan"
    )
    features: Mapped[list["BuyerRequirementFeature"]] = relationship(
        back_populates="buyer_requirement", cascade="all, delete-orphan"
    )

    __table_args__ = (
        _minmax_check("budget", "ck_buyer_requirements_budget_range"),
        _minmax_check("bedrooms", "ck_buyer_requirements_bedrooms_range"),
        _minmax_check("bathrooms", "ck_buyer_requirements_bathrooms_range"),
        _minmax_check("construction_m2", "ck_buyer_requirements_construction_m2_range"),
        _minmax_check("land_m2", "ck_buyer_requirements_land_m2_range"),
        Index("ix_buyer_requirements_organization_id", "organization_id"),
        Index("ix_buyer_requirements_contact_id", "contact_id"),
        Index("ix_buyer_requirements_status", "status"),
        Index("ix_buyer_requirements_property_type", "property_type"),
        Index("ix_buyer_requirements_budget_range", "budget_min", "budget_max"),
    )


class BuyerRequirementLocation(Base, UUIDPKMixin, CreatedAtMixin):
    """A requirement can list several acceptable areas, ranked by priority — never a single free-text field."""

    __tablename__ = "buyer_requirement_locations"

    buyer_requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("buyer_requirements.id", ondelete="CASCADE"), nullable=False
    )
    city: Mapped[str | None] = mapped_column(nullable=True)
    state: Mapped[str | None] = mapped_column(nullable=True)
    neighborhood: Mapped[str | None] = mapped_column(nullable=True)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    buyer_requirement: Mapped["BuyerRequirement"] = relationship(back_populates="locations")

    __table_args__ = (
        CheckConstraint(
            "city IS NOT NULL OR neighborhood IS NOT NULL", name="ck_buyer_requirement_locations_city_or_neighborhood"
        ),
        Index("ix_buyer_requirement_locations_requirement_id", "buyer_requirement_id"),
        Index("ix_buyer_requirement_locations_city_neighborhood", "city", "neighborhood"),
    )


class BuyerRequirementFeature(Base, UUIDPKMixin, CreatedAtMixin):
    """A requirement's must-have/preferred/deal-breaker features — see app.models.feature.Feature."""

    __tablename__ = "buyer_requirement_features"

    buyer_requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("buyer_requirements.id", ondelete="CASCADE"), nullable=False
    )
    feature_key: Mapped[str] = mapped_column(ForeignKey("features.key"), nullable=False)
    # Soft enum: must_have | preferred | deal_breaker.
    classification: Mapped[str] = mapped_column(nullable=False)

    buyer_requirement: Mapped["BuyerRequirement"] = relationship(back_populates="features")
    feature = relationship("Feature")

    __table_args__ = (
        UniqueConstraint(
            "buyer_requirement_id", "feature_key", name="uq_buyer_requirement_features_requirement_feature"
        ),
    )
