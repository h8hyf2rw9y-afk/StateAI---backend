import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from app.schemas.common import ORMModel
from app.schemas.enums import (
    BuyerRequirementPurpose,
    BuyerRequirementStatus,
    FeatureClassification,
    FinancingType,
    PreapprovalStatus,
    PropertyType,
    Timeline,
)

# Every (min, max) field pair validated the same way — mirrors the DB CHECK
# constraints in app/models/buyer_requirement.py, but gives a clean 422
# instead of a raw Postgres IntegrityError.
MINMAX_FIELDS = (
    "budget",
    "bedrooms",
    "bathrooms",
    "construction_m2",
    "land_m2",
)


def _validate_minmax_pairs(values: dict) -> None:
    for field in MINMAX_FIELDS:
        lo, hi = values.get(f"{field}_min"), values.get(f"{field}_max")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"{field}_min must be <= {field}_max.")


class BuyerRequirementBase(BaseModel):
    purpose: BuyerRequirementPurpose | None = None
    status: BuyerRequirementStatus = "active"
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    currency: str = "MXN"
    property_type: PropertyType | None = None
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    bathrooms_min: Decimal | None = None
    bathrooms_max: Decimal | None = None
    construction_m2_min: Decimal | None = None
    construction_m2_max: Decimal | None = None
    land_m2_min: Decimal | None = None
    land_m2_max: Decimal | None = None
    parking_spaces_min: int | None = None
    timeline: Timeline | None = None
    financing_type: FinancingType | None = None
    preapproval_status: PreapprovalStatus | None = None
    motivation: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_ranges(self) -> "BuyerRequirementBase":
        _validate_minmax_pairs(self.__dict__)
        return self


class BuyerRequirementCreate(BuyerRequirementBase):
    pass


class BuyerRequirementUpdate(BaseModel):
    purpose: BuyerRequirementPurpose | None = None
    status: BuyerRequirementStatus | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    currency: str | None = None
    property_type: PropertyType | None = None
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    bathrooms_min: Decimal | None = None
    bathrooms_max: Decimal | None = None
    construction_m2_min: Decimal | None = None
    construction_m2_max: Decimal | None = None
    land_m2_min: Decimal | None = None
    land_m2_max: Decimal | None = None
    parking_spaces_min: int | None = None
    timeline: Timeline | None = None
    financing_type: FinancingType | None = None
    preapproval_status: PreapprovalStatus | None = None
    motivation: str | None = None
    notes: str | None = None

    # Note: on a partial update, an unset bound stays at its existing DB
    # value — the service layer re-validates the *merged* min/max pair
    # (see buyer_requirement_service.update) since this schema alone can't
    # see the row's current values.


class LocationCreate(BaseModel):
    city: str | None = None
    state: str | None = None
    neighborhood: str | None = None
    priority: int = 1

    @model_validator(mode="after")
    def _require_city_or_neighborhood(self) -> "LocationCreate":
        if not self.city and not self.neighborhood:
            raise ValueError("At least one of city or neighborhood is required.")
        return self


class LocationRead(ORMModel):
    id: uuid.UUID
    city: str | None
    state: str | None
    neighborhood: str | None
    priority: int


class FeatureAssign(BaseModel):
    feature_key: str
    classification: FeatureClassification


class FeatureAssignRead(ORMModel):
    feature_key: str
    classification: str


class BuyerRequirementRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    contact_id: uuid.UUID
    purpose: str | None
    status: str
    budget_min: Decimal | None
    budget_max: Decimal | None
    currency: str
    property_type: str | None
    bedrooms_min: int | None
    bedrooms_max: int | None
    bathrooms_min: Decimal | None
    bathrooms_max: Decimal | None
    construction_m2_min: Decimal | None
    construction_m2_max: Decimal | None
    land_m2_min: Decimal | None
    land_m2_max: Decimal | None
    parking_spaces_min: int | None
    timeline: str | None
    financing_type: str | None
    preapproval_status: str | None
    motivation: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    locations: list[LocationRead] = []
    features: list[FeatureAssignRead] = []
