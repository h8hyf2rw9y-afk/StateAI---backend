from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.crypto import EncryptionNotConfiguredError, encrypt_secret, mask_encrypted
from app.models.renova_case import RenovaCase
from app.repositories.organization_repo import UserRepository
from app.repositories.renova_case_repo import RenovaCaseRepository
from app.schemas.renova_case import (
    FINANCIAL_FIELDS,
    RenovaCaseCreate,
    RenovaCaseListItem,
    RenovaCaseRead,
    RenovaCaseUpdate,
)
from app.services.audit_service import AuditService

_ENTITY_TYPE = "renova_case"

# Write-only inputs that map to encrypted columns. They are handled
# separately from every other field and never enter an audit snapshot.
_SENSITIVE_INPUTS = {"nss": "nss_encrypted", "credit_number": "credit_number_encrypted"}


class RenovaCaseService:
    """
    The Renova module's Backend Service — Route -> Service -> Repository, same
    shape as every other module. Independent of ContactService and friends on
    purpose: nothing here reads or writes Contacts, Buyer Requirements,
    Property Interests, Opportunities or Properties.

    Privacy rules enforced here (see also app/core/crypto.py):
      * NSS / credit number are encrypted before they touch the ORM object, so
        they never exist in plaintext past this method's input.
      * Responses only ever carry the masked form; listings carry nothing.
      * Audit snapshots are built by `_audit_snapshot`, which excludes both
        fields entirely (recording only that a sensitive field CHANGED, never
        its value).
      * No exception message or log line here includes user-supplied data.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RenovaCaseRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    # --- reads -------------------------------------------------------------

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        q: str | None = None,
        status_: str | None = None,
        assigned_user_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RenovaCaseListItem]:
        cases = self.repo.list(
            organization_id, q=q, status=status_, assigned_user_id=assigned_user_id, limit=limit, offset=offset
        )
        return [RenovaCaseListItem.model_validate(c) for c in cases]

    def get_or_404(self, organization_id: uuid.UUID, case_id: uuid.UUID) -> RenovaCase:
        case = self.repo.get(organization_id, case_id)
        if case is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Renova case not found.")
        return case

    def get(self, organization_id: uuid.UUID, case_id: uuid.UUID) -> RenovaCaseRead:
        return self.to_read(self.get_or_404(organization_id, case_id))

    # --- writes ------------------------------------------------------------

    def create(
        self, organization_id: uuid.UUID, data: RenovaCaseCreate, actor_user_id: uuid.UUID | None = None
    ) -> RenovaCaseRead:
        self._validate_assignee(organization_id, data.assigned_user_id)
        fields = data.model_dump(exclude={"nss", "credit_number"})
        encrypted = self._encrypt_inputs(
            {"nss": data.nss, "credit_number": data.credit_number}, only_set={"nss", "credit_number"}
        )
        case = self.repo.create(organization_id, created_by_user_id=actor_user_id, **fields, **encrypted)
        self.db.flush()
        self.db.refresh(case)
        self.audit.record(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            entity_type=_ENTITY_TYPE,
            entity_id=case.id,
            action="RENOVA_CASE_CREATED",
            after=self._audit_snapshot(case),
        )
        self.db.commit()
        self.db.refresh(case)
        return self.to_read(case)

    def update(
        self,
        organization_id: uuid.UUID,
        case_id: uuid.UUID,
        data: RenovaCaseUpdate,
        actor_user_id: uuid.UUID | None = None,
    ) -> RenovaCaseRead:
        case = self.get_or_404(organization_id, case_id)
        provided = data.model_dump(exclude_unset=True)
        if "assigned_user_id" in provided:
            self._validate_assignee(organization_id, provided["assigned_user_id"])

        before_snapshot = self._audit_snapshot(case)
        before_values = {f: getattr(case, f) for f in provided if f not in _SENSITIVE_INPUTS}

        sensitive_present = {k: getattr(data, k) for k in _SENSITIVE_INPUTS if k in data.model_fields_set}
        encrypted = self._encrypt_inputs(sensitive_present, only_set=set(sensitive_present))
        plain_updates = {k: v for k, v in provided.items() if k not in _SENSITIVE_INPUTS}

        self.repo.update(case, **plain_updates)
        # OrgScopedRepository.update skips None values, so an explicit null
        # (clearing an optional field, or a sensitive one) is applied here.
        for key, value in plain_updates.items():
            if value is None:
                setattr(case, key, None)
        for column, ciphertext in encrypted.items():
            setattr(case, column, ciphertext)
        self.db.flush()
        self.db.refresh(case)

        changed = {f for f, old in before_values.items() if getattr(case, f) != old}
        sensitive_changed = sorted(k for k in sensitive_present)  # names only, never values
        if changed or sensitive_changed:
            after_snapshot = self._audit_snapshot(case)
            self._record_update_audits(
                organization_id, actor_user_id, case.id, before_snapshot, after_snapshot, changed, sensitive_changed
            )

        self.db.commit()
        self.db.refresh(case)
        return self.to_read(case)

    # --- helpers -----------------------------------------------------------

    def to_read(self, case: RenovaCase) -> RenovaCaseRead:
        read = RenovaCaseRead.model_validate(case)
        return read.model_copy(
            update={
                "nss_masked": mask_encrypted(case.nss_encrypted),
                "credit_number_masked": mask_encrypted(case.credit_number_encrypted),
            }
        )

    def _validate_assignee(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Never trusts a client-supplied advisor id — it must be a user of THIS organization. 404 (not 403) so another org's user ids can't be probed."""
        user = self.user_repo.get(user_id)
        if user is None or user.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Advisor not found.")

    def _encrypt_inputs(self, values: dict[str, Any], *, only_set: set[str]) -> dict[str, str | None]:
        """{"nss": SecretStr|None, ...} -> {"nss_encrypted": ciphertext|None}. None clears; missing key is left alone."""
        out: dict[str, str | None] = {}
        for name in only_set:
            secret = values.get(name)
            column = _SENSITIVE_INPUTS[name]
            if secret is None:
                out[column] = None
                continue
            try:
                out[column] = encrypt_secret(secret.get_secret_value())
            except EncryptionNotConfiguredError:
                # Static message on purpose; the value is never stored unencrypted.
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "Sensitive-field encryption is not configured."
                ) from None
        return out

    def _audit_snapshot(self, case: RenovaCase) -> dict:
        """
        The Read-schema shape (the convention every other service follows)
        minus the two masked fields, plus two booleans so the diff can show
        that a sensitive field was set/cleared without revealing anything
        about it — not even its last four characters.
        """
        snapshot = RenovaCaseRead.model_validate(case).model_dump(mode="json")
        snapshot.pop("nss_masked", None)
        snapshot.pop("credit_number_masked", None)
        snapshot["has_nss"] = case.nss_encrypted is not None
        snapshot["has_credit_number"] = case.credit_number_encrypted is not None
        return snapshot

    def _record_update_audits(
        self,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        case_id: uuid.UUID,
        before: dict,
        after: dict,
        changed: set[str],
        sensitive_changed: list[str],
    ) -> None:
        def record(action: str, extra_after: dict | None = None) -> None:
            self.audit.record(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                entity_type=_ENTITY_TYPE,
                entity_id=case_id,
                action=action,
                before=before,
                after={**after, **(extra_after or {})},
            )

        # One general row for any edit, plus a specific row for each of the
        # changes the product wants to be able to find on their own.
        record("RENOVA_CASE_UPDATED", {"sensitive_fields_changed": sensitive_changed} if sensitive_changed else None)
        if "status" in changed:
            record("RENOVA_CASE_STATUS_CHANGED")
        if "assigned_user_id" in changed:
            record("RENOVA_CASE_ASSIGNEE_CHANGED")
        if changed & set(FINANCIAL_FIELDS):
            record("RENOVA_CASE_FINANCIALS_UPDATED")
