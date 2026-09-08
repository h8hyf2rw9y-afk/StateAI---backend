import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.enums import PropertyStatus, PropertyType


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
    created_at: datetime
    updated_at: datetime
    features: list[PropertyFeatureRead] = []


class PropertyFeatureAssign(BaseModel):
    feature_key: str
