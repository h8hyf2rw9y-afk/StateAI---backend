from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.automation.actions import create_activity
from app.models.appointment import Appointment
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.opportunity_repo import OpportunityRepository
from app.repositories.property_repo import PropertyRepository
from app.schemas.appointment import AppointmentCreate, AppointmentRead, AppointmentUpdate
from app.services.audit_service import AuditService

# appointment_type -> the closest real ActivityType (app/schemas/enums.py).
# "showing" is the only appointment type with a direct match; every other
# type (call/meeting/notary/signing/other) becomes a generic "meeting" —
# there's no ActivityType for "notary"/"signing" specifically, and
# inventing one wasn't part of this phase's brief (a new soft-enum value
# would still be a schema addition to justify, not a free import).
_OUTCOME_ACTIVITY_TYPE_BY_APPOINTMENT_TYPE = {"showing": "property_viewing"}
_DEFAULT_OUTCOME_ACTIVITY_TYPE = "meeting"


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite (the test DB) drops tzinfo on round-trip even for a DateTime(timezone=True) column, unlike real Postgres — same quirk app/services/lead_context_service.py's _engagement_summary already works around, needed here since one operand may come straight off the ORM object and the other straight off the incoming (aware) request body."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _check_start_before_end(start_at: datetime, end_at: datetime) -> None:
    """
    Validated against the *merged* row (existing values + whatever the
    partial update actually changed) — same reasoning as
    BuyerRequirementUpdate's min/max check. Deliberately called BEFORE
    OrgScopedRepository.update()'s flush, not after: the model's own
    ck_appointments_start_before_end CheckConstraint would otherwise fire
    first on flush and surface as a generic 409 (via the global IntegrityError
    handler — app/core/errors.py) instead of this specific, friendly 422.
    """
    if _as_aware_utc(start_at) > _as_aware_utc(end_at):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "start_at must be before or equal to end_at.")


class AppointmentService:
    """A scheduled/planned event — see app/models/appointment.py for why this is deliberately not an Activity."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AppointmentRepository(db)
        self.contact_repo = ContactRepository(db)
        self.property_repo = PropertyRepository(db)
        self.opportunity_repo = OpportunityRepository(db)
        self.audit = AuditService(db)

    def list(self, organization_id: uuid.UUID, **filters) -> list[Appointment]:
        return self.repo.list(organization_id, **filters)

    def get_or_404(self, organization_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment:
        appointment = self.repo.get(organization_id, appointment_id)
        if appointment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")
        return appointment

    def _validate_references(self, organization_id: uuid.UUID, data) -> None:
        if data.contact_id is not None and self.contact_repo.get(organization_id, data.contact_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")
        if data.property_id is not None and self.property_repo.get(organization_id, data.property_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found.")
        if data.opportunity_id is not None and self.opportunity_repo.get(organization_id, data.opportunity_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found.")

    def create(
        self, organization_id: uuid.UUID, data: AppointmentCreate, actor_user_id: uuid.UUID | None
    ) -> Appointment:
        self._validate_references(organization_id, data)
        appointment = self.repo.create(organization_id, created_by_user_id=actor_user_id, **data.model_dump())
        after = AppointmentRead.model_validate(appointment).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="appointment",
            entity_id=appointment.id,
            action="APPOINTMENT_CREATED",
            after=after,
        )
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def update(
        self,
        organization_id: uuid.UUID,
        appointment_id: uuid.UUID,
        data: AppointmentUpdate,
        actor_user_id: uuid.UUID | None,
    ) -> Appointment:
        appointment = self.get_or_404(organization_id, appointment_id)
        self._validate_references(organization_id, data)
        before = AppointmentRead.model_validate(appointment).model_dump(mode="json")

        fields = data.model_dump(exclude_unset=True)
        # Not a real Appointment column (app/models/appointment.py is
        # unchanged) — see AppointmentUpdate.outcome_notes's own docstring.
        # Popped before repo.update so it's never passed to setattr().
        outcome_notes = fields.pop("outcome_notes", None)
        merged_start = fields.get("start_at", appointment.start_at)
        merged_end = fields.get("end_at", appointment.end_at)
        _check_start_before_end(merged_start, merged_end)

        updated = self.repo.update(appointment, **fields)
        after = AppointmentRead.model_validate(updated).model_dump(mode="json")
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="appointment",
            entity_id=updated.id,
            action="APPOINTMENT_UPDATED",
            before=before,
            after=after,
        )
        self.db.commit()
        self.db.refresh(updated)

        # Phase 5 — User Story F/K: recording a completed showing's outcome
        # in the same PATCH that marks it completed, instead of two
        # separate manual steps. Only fires when there's a real contact to
        # attach the Activity to (Activity.contact_id is required — never
        # fabricated) and the merged status actually is "completed"; a
        # human can still resend outcome_notes on an already-completed
        # appointment (e.g. to add detail) and get another real Activity —
        # deliberately stateless, no hidden "already recorded" flag, so the
        # caller stays in full control of when a note becomes history.
        merged_status = fields.get("status", appointment.status)
        if outcome_notes and merged_status == "completed" and updated.contact_id is not None:
            activity_type = _OUTCOME_ACTIVITY_TYPE_BY_APPOINTMENT_TYPE.get(
                updated.appointment_type, _DEFAULT_OUTCOME_ACTIVITY_TYPE
            )
            create_activity(
                self.db,
                organization_id,
                contact_id=updated.contact_id,
                activity_type=activity_type,
                notes=outcome_notes,
                occurred_at=datetime.now(timezone.utc),
                property_id=updated.property_id,
                opportunity_id=updated.opportunity_id,
                actor_user_id=actor_user_id,
            )

        return updated

    def delete(self, organization_id: uuid.UUID, appointment_id: uuid.UUID, actor_user_id: uuid.UUID | None) -> None:
        appointment = self.get_or_404(organization_id, appointment_id)
        before = AppointmentRead.model_validate(appointment).model_dump(mode="json")
        deleted_id = appointment.id
        self.repo.delete(appointment)
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type="appointment",
            entity_id=deleted_id,
            action="APPOINTMENT_DELETED",
            before=before,
        )
        self.db.commit()
