"""
Initial rows for the `roles` and `features` catalog tables — both are
referenced by foreign keys (contact_roles.role_key, property_features/
buyer_requirement_features.feature_key), so without these seeded, Postgres
rejects every insert that references them. This is the single source of
truth both the Alembic migration and the test fixtures seed from, so the
two can't drift apart.

`ROLE_SEEDS` mirrors CONTACT_ROLE_KEYS in app/schemas/enums.py. `FEATURE_SEEDS`
is the example feature set from the project brief — extend it by adding a
row here (and via a small follow-up migration/insert), never a schema change.
"""

ROLE_SEEDS: list[dict[str, str]] = [
    {"key": "buyer", "label": "Buyer"},
    {"key": "seller", "label": "Seller"},
    {"key": "owner", "label": "Owner"},
    {"key": "investor", "label": "Investor"},
    {"key": "agent", "label": "Agent"},
    {"key": "other", "label": "Other"},
]

FEATURE_SEEDS: list[dict[str, str]] = [
    {"key": "garden", "label": "Garden"},
    {"key": "pool", "label": "Pool"},
    {"key": "terrace", "label": "Terrace"},
    {"key": "home_office", "label": "Home Office"},
    {"key": "maid_quarters", "label": "Maid's Quarters"},
    {"key": "laundry_room", "label": "Laundry Room"},
    {"key": "security", "label": "Security"},
    {"key": "elevator", "label": "Elevator"},
    {"key": "balcony", "label": "Balcony"},
    {"key": "pet_friendly", "label": "Pet Friendly"},
    {"key": "gated_community", "label": "Gated Community"},
]
