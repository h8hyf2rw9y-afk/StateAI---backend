import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from app.schemas.common import ORMModel
from app.schemas.enums import PropertyCollaborationStatus, PropertyOwnershipType, PropertyStatus, PropertyType


class PropertyBase(BaseModel):
    title: str
    property_type: PropertyType
    status: PropertyStatus = "draft"
    price: Decimal | None = None
    currency: str = "MXN"
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    neighborhood: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    construction_m2: Decimal | None = None
    land_m2: Decimal | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    parking_spaces: int | None = None
    description: str | None = None
    # See app/models/property.py's own docstring for the full reasoning.
    ownership_type: PropertyOwnershipType = "own"
    external_source: str | None = None
    external_advisor_name: str | None = None
    external_advisor_contact: str | None = None
    collaboration_status: PropertyCollaborationStatus | None = None

    @model_validator(mode="after")
    def _external_fields_require_external_ownership(self) -> "PropertyBase":
        """Mirrors BuyerRequirementBase's own min/max validator style: a cheap, honest guard against data that would silently mean nothing (collaboration details on a property marked as the advisor's own)."""
        if self.ownership_type == "own" and self.collaboration_status is not None:
            raise ValueError("collaboration_status only applies to an external (ownership_type='external') property.")
        return self


class PropertyCreate(PropertyBase):
    pass


class PropertyUpdate(BaseModel):
    title: str | None = None
    property_type: PropertyType | None = None
    status: PropertyStatus | None = None
    price: Decimal | None = None
    currency: str | None = None
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    neighborhood: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    construction_m2: Decimal | None = None
    land_m2: Decimal | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    parking_spaces: int | None = None
    description: str | None = None
    ownership_type: PropertyOwnershipType | None = None
    external_source: str | None = None
    external_advisor_name: str | None = None
    external_advisor_contact: str | None = None
    collaboration_status: PropertyCollaborationStatus | None = None


class PropertyFeatureRead(ORMModel):
    feature_key: str


class PropertyRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    property_type: str
    status: str
    price: Decimal | None
    currency: str
    address_line: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    neighborhood: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    construction_m2: Decimal | None
    land_m2: Decimal | None
    bedrooms: int | None
    bathrooms: Decimal | None
    parking_spaces: int | None
    description: str | None
    ownership_type: str
    external_source: str | None
    external_advisor_name: str | None
    external_advisor_contact: str | None
    collaboration_status: str | None
    created_at: datetime
    updated_at: datetime
    features: list[PropertyFeatureRead] = []


class PropertyFeatureAssign(BaseModel):
    feature_key: str
