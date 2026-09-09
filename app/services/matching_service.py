from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.buyer_requirement import BuyerRequirement
from app.models.property import Property
from app.schemas.matching import PropertyMatchAnalysis
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

    # ------------------------------------------------------------------
    # Richer, explainable analysis — GET /buyer-requirements/{id}/property-matches
    # ------------------------------------------------------------------
    #
    # Deliberately a *separate* method from find_matches above, not a
    # replacement: find_matches silently excludes any property that fails
    # one of its SQL WHERE clauses, which is exactly right for "give me a
    # short candidate list" but structurally can't explain *why* a
    # property was excluded (it was never fetched in the first place).
    # analyze_matches instead fetches every active property in the
    # organization and evaluates each one criterion-by-criterion in
    # Python, so every property — including ones that don't match at all —
    # gets a real, inspectable explanation. Still fully deterministic, no
    # AI, no embeddings: the same soft-enum/nullable-field data
    # find_matches already reads, just evaluated per-criterion instead of
    # folded into one combined SQL filter.

    def analyze_matches(
        self, organization_id: uuid.UUID, requirement_id: uuid.UUID, *, limit: int = 20
    ) -> list[PropertyMatchAnalysis]:
        requirement = self.requirement_service.get_or_404(organization_id, requirement_id)

        stmt = (
            select(Property)
            .where(Property.organization_id == organization_id, Property.status == "active")
            .options(selectinload(Property.features))
        )
        candidates = list(self.db.execute(stmt).scalars().all())

        analyses = [_analyze_one(requirement, prop) for prop in candidates]

        _CLASSIFICATION_RANK = {"match": 0, "partial_match": 1, "no_match": 2}
        analyses.sort(key=lambda a: (_CLASSIFICATION_RANK[a.classification], -len(a.criteria_met)))
        return analyses[:limit]


# --- criterion evaluation -------------------------------------------------------------
#
# Every _evaluate_* helper below returns None when the requirement doesn't
# specify that criterion at all (no preference — never counted as met or
# unmet, per "don't invent a judgment the data doesn't support"), or an
# (is_met, explanation) pair when it does. A property's own field being
# NULL where the requirement *does* specify a preference is treated as
# "unmet, unconfirmable" — the same philosophy find_matches above already
# established ("a property with an unset budget/bedroom count can't be
# confirmed to satisfy a requirement"), just with a distinguishable
# explanation string instead of a silent SQL exclusion.


def _evaluate_range(
    value: Decimal | int | None,
    req_min: Decimal | int | None,
    req_max: Decimal | int | None,
    label: str,
    unit: str = "",
) -> tuple[bool, str] | None:
    if req_min is None and req_max is None:
        return None
    if value is None:
        return False, f"{label} is not on file for this property, so it can't be confirmed against the client's requirement."
    if req_min is not None and value < req_min:
        return False, f"{label} ({value}{unit}) is below the client's minimum of {req_min}{unit}."
    if req_max is not None and value > req_max:
        return False, f"{label} ({value}{unit}) is above the client's maximum of {req_max}{unit}."
    bound = f"{req_min}{unit}+" if req_max is None else (f"up to {req_max}{unit}" if req_min is None else f"{req_min}-{req_max}{unit}")
    return True, f"{label} ({value}{unit}) fits the client's requirement ({bound})."


def _evaluate_budget(requirement: BuyerRequirement, prop: Property) -> tuple[bool, str] | None:
    if requirement.budget_min is None and requirement.budget_max is None:
        return None
    if requirement.currency != prop.currency:
        return False, (
            f"Listed in {prop.currency}, but the client's budget is specified in {requirement.currency} — "
            "currency conversion isn't performed, so this can't be confirmed."
        )
    if prop.price is None:
        return False, "This property has no listed price, so it can't be confirmed to be within budget."
    if requirement.budget_min is not None and prop.price < requirement.budget_min:
        return False, f"Price ({prop.price} {prop.currency}) is below the client's minimum budget of {requirement.budget_min}."
    if requirement.budget_max is not None and prop.price > requirement.budget_max:
        return False, f"Price ({prop.price} {prop.currency}) is above the client's maximum budget of {requirement.budget_max}."
    return True, f"Price ({prop.price} {prop.currency}) is within budget."


def _evaluate_property_type(requirement: BuyerRequirement, prop: Property) -> tuple[bool, str] | None:
    if not requirement.property_type:
        return None
    if prop.property_type == requirement.property_type:
        return True, f"Property type matches ({prop.property_type})."
    return False, f"Property type is {prop.property_type}, but the client is looking for {requirement.property_type}."


def _evaluate_location_field(
    locations: list, field: str, prop_value: str | None, label: str
) -> tuple[bool, str] | None:
    """`locations` is a BuyerRequirement.locations list — any one entry specifying this field is enough to make the criterion "specified"; any one entry's value matching the property is enough to satisfy it (same OR-across-locations philosophy find_matches already uses)."""
    wanted = {getattr(loc, field) for loc in locations if getattr(loc, field)}
    if not wanted:
        return None
    if prop_value and prop_value in wanted:
        return True, f"{label} matches ({prop_value})."
    wanted_list = ", ".join(sorted(wanted))
    if prop_value:
        return False, f"{label} is {prop_value}, but the client is looking in: {wanted_list}."
    return False, f"This property has no {label.lower()} on file, but the client is looking in: {wanted_list}."


def _analyze_one(requirement: BuyerRequirement, prop: Property) -> PropertyMatchAnalysis:
    criteria_met: list[str] = []
    criteria_unmet: list[str] = []
    hard_disqualified = False

    def _record(result: tuple[bool, str] | None) -> None:
        if result is None:
            return
        is_met, explanation = result
        (criteria_met if is_met else criteria_unmet).append(explanation)

    _record(_evaluate_property_type(requirement, prop))
    _record(_evaluate_budget(requirement, prop))
    _record(_evaluate_location_field(requirement.locations, "city", prop.city, "City"))
    _record(_evaluate_location_field(requirement.locations, "state", prop.state, "State"))
    _record(_evaluate_location_field(requirement.locations, "neighborhood", prop.neighborhood, "Neighborhood"))
    _record(_evaluate_range(prop.bedrooms, requirement.bedrooms_min, requirement.bedrooms_max, "Bedrooms"))
    _record(_evaluate_range(prop.bathrooms, requirement.bathrooms_min, requirement.bathrooms_max, "Bathrooms"))
    _record(_evaluate_range(prop.parking_spaces, requirement.parking_spaces_min, None, "Parking spaces"))
    _record(
        _evaluate_range(
            prop.construction_m2, requirement.construction_m2_min, requirement.construction_m2_max, "Construction area", " m²"
        )
    )
    _record(_evaluate_range(prop.land_m2, requirement.land_m2_min, requirement.land_m2_max, "Land area", " m²"))

    # Features: must_have and deal_breaker are hard overrides (same
    # philosophy find_matches already established for must_have — a
    # missing required feature, or the presence of one the client
    # explicitly ruled out, isn't a soft scoring penalty); preferred
    # features are evaluated individually, not folded into one aggregate
    # count, so each one is its own explainable criterion.
    prop_feature_keys = {f.feature_key for f in prop.features}
    for f in requirement.features:
        has_it = f.feature_key in prop_feature_keys
        if f.classification == "must_have":
            if has_it:
                criteria_met.append(f"Has required feature: {f.feature_key}.")
            else:
                criteria_unmet.append(f"Missing required feature: {f.feature_key}.")
                hard_disqualified = True
        elif f.classification == "deal_breaker":
            if has_it:
                criteria_unmet.append(f"Has a feature the client explicitly doesn't want: {f.feature_key}.")
                hard_disqualified = True
            else:
                criteria_met.append(f"Correctly does not have: {f.feature_key}.")
        elif f.classification == "preferred":
            if has_it:
                criteria_met.append(f"Has preferred feature: {f.feature_key}.")
            else:
                criteria_unmet.append(f"Missing preferred feature: {f.feature_key}.")

    total = len(criteria_met) + len(criteria_unmet)
    if hard_disqualified:
        classification = "no_match"
    elif total == 0:
        # The requirement specifies nothing comparable at all — neither a
        # match nor a mismatch can honestly be claimed from zero criteria.
        classification = "partial_match"
    elif len(criteria_unmet) == 0:
        classification = "match"
    elif len(criteria_met) == 0:
        classification = "no_match"
    else:
        classification = "partial_match"

    if total == 0:
        summary = "This search doesn't specify any comparable criteria yet."
    elif classification == "match":
        summary = f"Matches all {total} specified criteria."
    elif classification == "no_match":
        summary = f"Matches none of the {total} specified criteria." if not hard_disqualified else criteria_unmet[0]
    else:
        summary = f"Matches {len(criteria_met)} of {total} specified criteria."

    return PropertyMatchAnalysis(
        property=prop,
        classification=classification,
        criteria_met=criteria_met,
        criteria_unmet=criteria_unmet,
        summary=summary,
    )
