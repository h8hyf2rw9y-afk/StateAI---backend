from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.property import Property
from app.services.buyer_requirement_service import BuyerRequirementService


@dataclass
class PropertyMatch:
    """A candidate property plus how it scored — not a DB row, just a return shape for the /matches endpoint."""

    property: Property
    matched_preferred_features: int
    total_preferred_features: int


class MatchingService:
    """
    Use Case 5: "find properties matching Juan's requirements" — a
    deterministic SQL query, no AI. Every numeric threshold treats a NULL
    property value as "doesn't qualify" (a property with an unset budget/
    bedroom count can't be confirmed to satisfy a requirement, so it isn't
    offered as a match) — this keeps every filter consistent rather than
    special-casing some fields as lenient and others as strict.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.requirement_service = BuyerRequirementService(db)

    def find_matches(
        self, organization_id: uuid.UUID, requirement_id: uuid.UUID, *, limit: int = 20
    ) -> list[PropertyMatch]:
        requirement = self.requirement_service.get_or_404(organization_id, requirement_id)

        must_have_keys = {f.feature_key for f in requirement.features if f.classification == "must_have"}
        preferred_keys = {f.feature_key for f in requirement.features if f.classification == "preferred"}

        stmt = select(Property).where(
            Property.organization_id == organization_id,
            Property.status == "active",
        )

        if requirement.property_type:
            stmt = stmt.where(Property.property_type == requirement.property_type)
        if requirement.budget_min is not None:
            stmt = stmt.where(Property.price >= requirement.budget_min)
        if requirement.budget_max is not None:
            stmt = stmt.where(Property.price <= requirement.budget_max)
        if requirement.bedrooms_min is not None:
            stmt = stmt.where(Property.bedrooms >= requirement.bedrooms_min)
        if requirement.bathrooms_min is not None:
            stmt = stmt.where(Property.bathrooms >= requirement.bathrooms_min)
        if requirement.construction_m2_min is not None:
            stmt = stmt.where(Property.construction_m2 >= requirement.construction_m2_min)
        if requirement.land_m2_min is not None:
            stmt = stmt.where(Property.land_m2 >= requirement.land_m2_min)
        if requirement.parking_spaces_min is not None:
            stmt = stmt.where(Property.parking_spaces >= requirement.parking_spaces_min)

        # Any one of the requirement's preferred locations is enough to qualify.
        # No locations on the requirement at all means "no location filter".
        location_filters = []
        for loc in requirement.locations:
            if loc.city and loc.neighborhood:
                location_filters.append(and_(Property.city == loc.city, Property.neighborhood == loc.neighborhood))
            elif loc.neighborhood:
                location_filters.append(Property.neighborhood == loc.neighborhood)
            elif loc.city:
                location_filters.append(Property.city == loc.city)
        if location_filters:
            stmt = stmt.where(or_(*location_filters))

        stmt = stmt.options(selectinload(Property.features))
        candidates = list(self.db.execute(stmt).scalars().all())

        matches: list[PropertyMatch] = []
        for prop in candidates:
            prop_feature_keys = {f.feature_key for f in prop.features}
            # A missing must_have feature is a hard disqualifier, not a scoring penalty.
            if must_have_keys and not must_have_keys.issubset(prop_feature_keys):
                continue
            matches.append(
                PropertyMatch(
                    property=prop,
                    matched_preferred_features=len(preferred_keys & prop_feature_keys),
                    total_preferred_features=len(preferred_keys),
                )
            )

        matches.sort(key=lambda m: m.matched_preferred_features, reverse=True)
        return matches[:limit]