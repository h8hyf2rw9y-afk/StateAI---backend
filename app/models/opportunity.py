import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Opportunity(Base, UUIDPKMixin, TimestampMixin):
    """
    The actual sales process an advisor is actively managing — distinct
    from both BuyerRequirement ("what a contact is looking for", Case B)
    and PropertyInterest ("a contact's interest in one specific listing",
    Case A). A BuyerRequirement or PropertyInterest can exist without any
    commercial process yet being actively worked; an Opportunity is that
    process. A Contact can have several over time (tried to buy one house,
    lost it, is now searching again, later sells their own property) — each
    is its own row, never overwritten in place, mirroring how
    BuyerRequirement already handles "the same contact, a new search"
    (see Sergio's cancelled+active pair in the demo data).

    No client information is duplicated here — `contact_id`/`property_id`/
    `buyer_requirement_id` are foreign keys, read through when needed, same
    as every other relationship in this schema.
    """

    __tablename__ = "opportunities"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # CASCADE, not SET NULL: an Opportunity is fundamentally *about* a
    # contact (unlike property_id/buyer_requirement_id below, which are
    # optional context) — same reasoning already applied to
    # BuyerRequirement.contact_id and PropertyInterest.contact_id.
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)

    # Both SET NULL, not CASCADE: an Opportunity is business history this
    # project's own convention says should never be casually destroyed (see
    # "no hard DELETE route" below) — deleting the property/buyer requirement
    # it once referenced must not take the Opportunity down with it, the
    # same reasoning Activity.property_id already established.
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"), nullable=True
    )
    buyer_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("buyer_requirements.id", ondelete="SET NULL"), nullable=True
    )

    # Soft enums (app/schemas/enums.py): opportunity_type (buy/sell), stage
    # (shared 13-value set; OPPORTUNITY_STAGES_BY_TYPE — enforced in
    # OpportunityService, not the database — says which apply to which type).
    opportunity_type: Mapped[str] = mapped_column(nullable=False)
    stage: Mapped[str] = mapped_column(nullable=False, default="qualification")

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)

    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(nullable=False, default="MXN")
    # 0-100, a percentage — see ck_opportunities_probability_range below.
    probability: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Auto-stamped by OpportunityService when stage becomes won/lost, and
    # cleared again if the opportunity is reopened — never set directly by
    # a client, same pattern as Task.completed_at.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft enum. Required whenever stage="lost" (enforced in the service,
    # not the database — a DB CHECK can't easily cross-reference two
    # columns' business meaning this conditionally without a trigger, which
    # would be exactly the kind of extra machinery this project avoids).
    lost_reason: Mapped[str | None] = mapped_column(nullable=True)

    # SET NULL for both: losing the assigned/creating user must not erase
    # the deal's own history, same reasoning as Task's equivalents.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 100)",
            name="ck_opportunities_probability_range",
        ),
        CheckConstraint(
            "expected_value IS NULL OR expected_value >= 0", name="ck_opportunities_expected_value_nonnegative"
        ),
        Index("ix_opportunities_organization_id", "organization_id"),
        Index("ix_opportunities_contact_id", "contact_id"),
        Index("ix_opportunities_property_id", "property_id"),
        Index("ix_opportunities_buyer_requirement_id", "buyer_requirement_id"),
        Index("ix_opportunities_owner_user_id", "owner_user_id"),
        Index("ix_opportunities_org_type_stage", "organization_id", "opportunity_type", "stage"),
        Index("ix_opportunities_org_owner", "organization_id", "owner_user_id"),
        Index("ix_opportunities_expected_close_date", "expected_close_date"),
    )
