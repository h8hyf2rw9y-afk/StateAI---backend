from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.buyer_requirement import (
    BuyerRequirement,
    BuyerRequirementFeature,
    BuyerRequirementLocation,
)
from app.repositories.base import OrgScopedRepository

_EAGER = (selectinload(BuyerRequirement.locations), selectinload(BuyerRequirement.features))


class BuyerRequirementRepository(OrgScopedRepository[BuyerRequirement]):
    model = BuyerRequirement

    def get(self, organization_id: uuid.UUID, id: uuid.UUID) -> BuyerRequirement | None:
        stmt = (
            select(BuyerRequirement)
            .options(*_EAGER)
            .where(BuyerRequirement.id == id, BuyerRequirement.organization_id == organization_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[BuyerRequirement]:
        stmt = (
            select(BuyerRequirement)
            .options(*_EAGER)
            .where(BuyerRequirement.organization_id == organization_id)
            .order_by(BuyerRequirement.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_contact(self, organization_id: uuid.UUID, contact_id: uuid.UUID) -> list[BuyerRequirement]:
        stmt = (
            select(BuyerRequirement)
            .options(*_EAGER)
            .where(
                BuyerRequirement.organization_id == organization_id,
                BuyerRequirement.contact_id == contact_id,
            )
            .order_by(BuyerRequirement.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_location(self, requirement: BuyerRequirement, **fields) -> BuyerRequirementLocation:
        """
        Upserts by (city, state, neighborhood) — same pattern as add_feature below —
        rather than letting a repeat POST hit the DB's unique index
        (uq_buyer_requirement_locations_requirement_place in app/models/buyer_requirement.py)
        as a raw IntegrityError. Re-adding the same place just updates its priority,
        which is what a caller re-submitting the same location almost certainly wants.
        """
        existing = next(
            (
                loc
                for loc in requirement.locations
                if loc.city == fields.get("city")
                and loc.state == fields.get("state")
                and loc.neighborhood == fields.get("neighborhood")
            ),
            None,
        )
        if existing:
            existing.priority = fields.get("priority", existing.priority)
            self.db.flush()
            return existing
        location = BuyerRequirementLocation(buyer_requirement_id=requirement.id, **fields)
        self.db.add(location)
        self.db.flush()
        return location

    def add_feature(self, requirement: BuyerRequirement, feature_key: str, classification: str) -> BuyerRequirementFeature:
        existing = next((f for f in requirement.features if f.feature_key == feature_key), None)
        if existing:
            existing.classification = classification
            self.db.flush()
            return existing
        feature = BuyerRequirementFeature(
            buyer_requirement_id=requirement.id, feature_key=feature_key, classification=classification
        )
        self.db.add(feature)
        self.db.flush()
        return feature

    def remove_location(self, requirement: BuyerRequirement, location_id: uuid.UUID) -> None:
        """
        Mirrors PropertyRepository.remove_feature/ContactRepository.remove_role:
        only searches within `requirement`'s own already-loaded `locations`, so a
        location belonging to a different requirement (or a different org's
        requirement, which never loads here in the first place — see
        BuyerRequirementService.remove_location's get_or_404) is a silent no-op,
        never a cross-requirement delete.
        """
        location = next((loc for loc in requirement.locations if loc.id == location_id), None)
        if location:
            self.db.delete(location)
            self.db.flush()

    def remove_feature(self, requirement: BuyerRequirement, feature_key: str) -> None:
        """Removes the buyer_requirement_features row only — never the global Feature catalog row."""
        feature = next((f for f in requirement.features if f.feature_key == feature_key), None)
        if feature:
            self.db.delete(feature)
            self.db.flush()