from pydantic import BaseModel

from app.schemas.property import PropertyRead


class PropertyMatchRead(BaseModel):
    property: PropertyRead
    matched_preferred_features: int
    total_preferred_features: int
