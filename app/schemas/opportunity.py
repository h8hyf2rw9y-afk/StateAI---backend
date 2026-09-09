import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.enums import OpportunityLostReason, OpportunityStage, OpportunityType


class OpportunityCreate(BaseModel):
    """
    Created under a contact (`POST /contacts/{contact_id}/opportunities`) —
    contact_id comes from the URL, same pattern as BuyerRequirement/
    PropertyInterest/Activity, never from this body. `opportunity_type` is
    the one field this schema requires that those don't: every Opportunity
    is either a `buy` or a `sell` process from the moment it's created.
    """

    opportunity_type: OpportunityType
    property_id: uuid.UUID | None = None
    buyer_requirement_id: uuid.UUID | None = None
    stage: OpportunityStage = "qualification"
    title: str
    description: str | None = None
    expected_value: Decimal | None = Field(default=None, ge=0)
    currency: str = "MXN"
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: datetime | None = None
    lost_reason: OpportunityLostReason | None = None
    # Optional: defaults to the authenticated caller if omitted — see
    # OpportunityService.create. Explicit so a manager can create/assign an
    # opportunity to someone else.
    owner_user_id: uuid.UUID | None = None


class OpportunityUpdate(BaseModel):
    """
    All fields optional — PATCH semantics. `opportunity_type` and
    `contact_id` are deliberately NOT here: an opportunity's fundamental
    kind (buy vs. sell) and who it's about don't change after creation — if
    the type is wrong, create a new Opportunity (the domain already expects
    a contact to have several over time, see app/models/opportunity.py).

    Setting `stage` to "won"/"lost" auto-stamps `closed_at` server-side
    unless given explicitly; moving away from a closed stage (reopening)
    clears `closed_at`/`lost_reason` again — see OpportunityService.update.
    `lost_reason` is required (enforced service-side, not here, since it
    depends on the *resulting* stage) whenever stage ends up "lost".
    """

    property_id: uuid.UUID | None = None
    buyer_requirement_id: uuid.UUID | None = None
    stage: OpportunityStage | None = None
    title: str | None = None
    description: str | None = None
    expected_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: datetime | None = None
    lost_reason: OpportunityLostReason | None = None
    owner_user_id: uuid.UUID | None = None


class OpportunityRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    contact_id: uuid.UUID
    property_id: uuid.UUID | None
    buyer_requirement_id: uuid.UUID | None
    opportunity_type: str
    stage: str
    title: str
    description: str | None
    expected_value: Decimal | None
    currency: str
    probability: int | None
    expected_close_date: datetime | None
    closed_at: datetime | None
    lost_reason: str | None
    owner_user_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
