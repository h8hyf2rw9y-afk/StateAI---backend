from datetime import datetime

from app.schemas.common import ORMModel


class FeatureRead(ORMModel):
    """The global feature catalog (app/models/feature.py) — the source of truth for
    both property_features and buyer_requirement_features' feature_key. See
    GET /features in app/api/routes/features.py."""

    key: str
    label: str
    category: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
