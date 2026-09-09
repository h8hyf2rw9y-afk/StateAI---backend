"""
Initial rows for the `roles` and `features` catalog tables — both are
referenced by foreign keys (contact_roles.role_key, property_features/
buyer_requirement_features.feature_key), so without these seeded, Postgres
rejects every insert that references them. This is the single source of
truth both the Alembic migration and the test fixtures seed from, so the
two can't drift apart.

`ROLE_SEEDS` mirrors CONTACT_ROLE_KEYS in app/schemas/enums.py. `FEATURE_SEEDS`
is the example feature set from the project brief, now with `category`
(app/schemas/enums.py's FEATURE_CATEGORIES) and `is_active` alongside each
one — extend it by adding a row here (and via a small follow-up
migration/insert for an already-deployed database — see
alembic/versions/*_add_feature_catalog_fields.py's data backfill for the
rows that predate this), never a schema change.
"""

ROLE_SEEDS: list[dict[str, str]] = [
    {"key": "buyer", "label": "Buyer"},
    {"key": "seller", "label": "Seller"},
    {"key": "owner", "label": "Owner"},
    {"key": "investor", "label": "Investor"},
    {"key": "agent", "label": "Agent"},
    {"key": "other", "label": "Other"},
]

FEATURE_SEEDS: list[dict[str, object]] = [
    {"key": "garden", "label": "Garden", "category": "exterior", "is_active": True},
    {"key": "pool", "label": "Pool", "category": "exterior", "is_active": True},
    {"key": "terrace", "label": "Terrace", "category": "exterior", "is_active": True},
    {"key": "balcony", "label": "Balcony", "category": "exterior", "is_active": True},
    {"key": "home_office", "label": "Home Office", "category": "interior", "is_active": True},
    {"key": "maid_quarters", "label": "Maid's Quarters", "category": "interior", "is_active": True},
    {"key": "laundry_room", "label": "Laundry Room", "category": "interior", "is_active": True},
    {"key": "elevator", "label": "Elevator", "category": "amenity", "is_active": True},
    {"key": "security", "label": "Security", "category": "security", "is_active": True},
    {"key": "gated_community", "label": "Gated Community", "category": "security", "is_active": True},
    {"key": "pet_friendly", "label": "Pet Friendly", "category": "other", "is_active": True},
]
