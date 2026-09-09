from typing import Literal

from pydantic import BaseModel

from app.schemas.property import PropertyRead


class PropertyMatchRead(BaseModel):
    """
    Use Case 5's original shape — see app/services/matching_service.py's
    `find_matches`: a hard SQL filter (a property either qualifies or is
    silently excluded), with only preferred-feature counts as a soft
    signal. Kept exactly as-is (still the response of
    `GET /buyer-requirements/{id}/matches`, still used by
    features/buyer-requirements/components/match-list.tsx) — not replaced,
    since existing tests and an existing frontend consumer both depend on
    its exact current behavior. `PropertyMatchAnalysis` below is a richer,
    separate analysis added alongside it, not a redesign of it.
    """

    property: PropertyRead
    matched_preferred_features: int
    total_preferred_features: int


MatchClassification = Literal["match", "partial_match", "no_match"]


class PropertyMatchAnalysis(BaseModel):
    """
    The response shape for `GET /buyer-requirements/{id}/property-matches`
    — see app/services/matching_service.py's `analyze_matches` for the full
    classification rule. Every property the organization actually has
    (status="active") gets one of these, not just the ones that happen to
    qualify: `classification` distinguishes "match" (every criterion the
    requirement actually specifies is satisfied), "partial_match" (some
    are), and "no_match" (none are, or a must-have feature is missing /
    a deal-breaker feature is present — see the service for why those two
    are a hard override regardless of how many other criteria matched).

    `criteria_met`/`criteria_unmet` are plain, human-readable sentences,
    not scored sub-fields — only for criteria the requirement actually
    specifies a value for (a requirement with no location preference, for
    instance, has no "city"/"neighborhood" entry in either list at all,
    for that property). There is no numeric score anywhere on this model,
    deliberately — see the module docstring.
    """

    property: PropertyRead
    classification: MatchClassification
    criteria_met: list[str]
    criteria_unmet: list[str]
    summary: str
