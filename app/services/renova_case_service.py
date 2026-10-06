from __future__ import annotations

import uuid
import base64
import binascii
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.renova_access import renova_owner_filter
from app.core.crypto import (
    EncryptionNotConfiguredError,
    SecretDecryptionError,
    encrypt_secret,
    mask_encrypted,
    reveal_secret,
)
from app.models.renova_case import RenovaCase
from app.repositories.organization_repo import UserRepository
from app.repositories.renova_case_repo import RenovaCaseRepository
from app.schemas.enums import RENOVA_CLOSED_STATUSES, RENOVA_OPERATION_STAGES, RENOVA_PIPELINE_STAGES
from app.schemas.renova_case import (
    FINANCIAL_FIELDS,
    RenovaCaseBucketCounts,
    RenovaCaseCreate,
    RenovaCaseListItem,
    RenovaCaseRead,
    RenovaCaseUpdate,
    RenovaPipelineCase,
    RenovaPipelineResponse,
    RenovaPipelineStage,
    RenovaSensitiveData,
)
from app.schemas.user import CurrentUser
from app.schemas.renova_operation import (
    RenovaOperationCase,
    RenovaOperationStageGroup,
    RenovaOperationsResponse,
    RenovaOperationUpdate,
)
from app.services.audit_service import AuditService
from app.services.renova_follow_up_service import RenovaFollowUpService

_ENTITY_TYPE = "renova_case"

# Write-only inputs that map to encrypted columns. They are handled
# separately from every other field and never enter an audit snapshot.
_SENSITIVE_INPUTS = {"nss": "nss_encrypted", "credit_number": "credit_number_encrypted"}

# Who may see the FULL protected values: organization owners and admins, and
# the advisor the case is assigned to. Any other member of the organization
# can work the case but only ever sees the masks.
_REVEAL_ROLES = ("owner", "admin")
_INE_COLUMNS = {"front": "ine_front_encrypted", "back": "ine_back_encrypted"}
_INE_DATA_URL = re.compile(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$")
_MAX_INE_BYTES = 2 * 1024 * 1024


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

    @staticmethod
    @contextmanager
    def _translate_crypto_errors() -> Iterator[None]:
        """Wraps an encrypt_secret/reveal_secret call so every caller reports the same two failure modes the same way, instead of repeating the try/except at each call site."""
        try:
            yield
        except EncryptionNotConfiguredError:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Sensitive-field encryption is not configured."
            ) from None
        except SecretDecryptionError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The stored protected data can't be decrypted with the configured key.",
            ) from None

    # --- reads -------------------------------------------------------------

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        q: str | None = None,
        status_: str | None = None,
        assigned_user_id: uuid.UUID | None = None,
        archived: bool | None = None,
        bucket: str | None = None,
        limit: int = 50,
        offset: int = 0,
        visible_to: uuid.UUID | None = None,
    ) -> list[RenovaCaseListItem]:
        cases = self.repo.list(
            organization_id,
            q=q,
            status=status_,
            assigned_user_id=assigned_user_id,
            archived=archived,
            bucket=bucket,
            limit=limit,
            offset=offset,
            visible_to=visible_to,
        )
        summaries = RenovaFollowUpService(self.db).summaries_for_cases(
            organization_id, [case.id for case in cases]
        )
        return [
            RenovaCaseListItem.model_validate(case).model_copy(update={"follow_up": summaries[case.id]})
            for case in cases
        ]

    def counts(self, organization_id: uuid.UUID, *, visible_to: uuid.UUID | None = None) -> RenovaCaseBucketCounts:
        """One cheap grouped query for the three Leads -> Renova tabs' counters (see RenovaCaseBucketCounts)."""
        return RenovaCaseBucketCounts(**self.repo.counts(organization_id, visible_to=visible_to))

    def pipeline(self, organization_id: uuid.UUID, *, visible_to: uuid.UUID | None = None) -> RenovaPipelineResponse:
        """
        The Renova Kanban board: every case actively moving through the
        purchase flow (RENOVA_PIPELINE_STAGES), grouped by stage in board
        order — one query, no pagination gap. "draft", "reviewing",
        "rejected" and "cancelled" cases are real and kept, just never on
        this board (see RENOVA_PIPELINE_STAGES's docstring).
        """
        cases = self.repo.list_for_pipeline(organization_id, RENOVA_PIPELINE_STAGES, visible_to=visible_to)
        by_status: dict[str, list[RenovaCase]] = {stage: [] for stage in RENOVA_PIPELINE_STAGES}
        for case in cases:
            by_status[case.status].append(case)
        return RenovaPipelineResponse(
            stages=[
                RenovaPipelineStage(status=stage, cases=[RenovaPipelineCase.model_validate(c) for c in by_status[stage]])
                for stage in RENOVA_PIPELINE_STAGES
            ]
        )

    def operations(
        self, organization_id: uuid.UUID, *, visible_to: uuid.UUID | None = None
    ) -> RenovaOperationsResponse:
        """Every live post-acceptance property, grouped by its operational stage."""
        cases = self.repo.list_for_operations(
            organization_id, RENOVA_OPERATION_STAGES, visible_to=visible_to
        )
        by_stage: dict[str, list[RenovaCase]] = {stage: [] for stage in RENOVA_OPERATION_STAGES}
        for case in cases:
            if case.operation_stage in by_stage:
                by_stage[case.operation_stage].append(case)
        return RenovaOperationsResponse(
            stages=[
                RenovaOperationStageGroup(
                    stage=stage,
                    cases=[RenovaOperationCase.model_validate(case) for case in by_stage[stage]],
                )
                for stage in RENOVA_OPERATION_STAGES
            ]
        )

    def update_operation(
        self,
        organization_id: uuid.UUID,
        case_id: uuid.UUID,
        data: RenovaOperationUpdate,
        actor_user_id: uuid.UUID | None = None,
        *,
        visible_to: uuid.UUID | None = None,
    ) -> RenovaOperationCase:
        case = self.get_or_404(organization_id, case_id, visible_to=visible_to)
        if case.archived or case.status in RENOVA_CLOSED_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Rejected, cancelled or archived cases cannot be moved through operations.",
            )
        if case.status not in ("accepted", "purchased"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "The proposal must be accepted before starting the property operation.",
            )

        provided = data.model_dump(exclude_unset=True)
        before = self._operation_snapshot(case)
        previous_stage = case.operation_stage
        for field, value in provided.items():
            setattr(case, field, value)

        if "operation_stage" in provided and case.operation_stage != previous_stage:
            case.operation_stage_updated_at = datetime.now(timezone.utc)
            stage_index = RENOVA_OPERATION_STAGES.index(case.operation_stage)
            renovation_index = RENOVA_OPERATION_STAGES.index("renovation")
            case.status = "purchased" if stage_index >= renovation_index else "accepted"

        self.db.flush()
        self.db.refresh(case)
        after = self._operation_snapshot(case)
        if before != after:
            self.audit.record(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                entity_type=_ENTITY_TYPE,
                entity_id=case.id,
                action=(
                    "RENOVA_OPERATION_STAGE_CHANGED"
                    if case.operation_stage != previous_stage
                    else "RENOVA_OPERATION_UPDATED"
                ),
                before=before,
                after=after,
            )
        self.db.commit()
        self.db.refresh(case)
        return RenovaOperationCase.model_validate(case)

    def get_or_404(
        self, organization_id: uuid.UUID, case_id: uuid.UUID, *, visible_to: uuid.UUID | None = None
    ) -> RenovaCase:
        """404 both for another organization's case and for a case a Renova-only advisor doesn't own — indistinguishable on purpose."""
        case = self.repo.get_visible(organization_id, case_id, visible_to=visible_to)
        if case is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Renova case not found.")
        return case

    def get(
        self, organization_id: uuid.UUID, case_id: uuid.UUID, *, visible_to: uuid.UUID | None = None
    ) -> RenovaCaseRead:
        return self.to_read(self.get_or_404(organization_id, case_id, visible_to=visible_to))

    def reveal_sensitive_data(self, current_user: CurrentUser, case_id: uuid.UUID) -> RenovaSensitiveData:
        """
        The only path that returns the full NSS / credit number. Order matters:
        the case is resolved inside the caller's own organization first (404
        for anything else, so ids of other organizations can't be probed), then
        authorization, and only then is anything decrypted. Each successful
        reveal is audited — who, which case, when — never the values, not even
        their last four characters.
        """
        case = self.get_or_404(current_user.organization_id, case_id, visible_to=renova_owner_filter(current_user))
        if current_user.role not in _REVEAL_ROLES and case.assigned_user_id != current_user.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You are not allowed to view this case's protected data."
            )
        with self._translate_crypto_errors():
            data = RenovaSensitiveData(
                nss=reveal_secret(case.nss_encrypted) if case.nss_encrypted else None,
                credit_number=reveal_secret(case.credit_number_encrypted) if case.credit_number_encrypted else None,
            )
        self.audit.record(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            entity_type=_ENTITY_TYPE,
            entity_id=case.id,
            action="RENOVA_SENSITIVE_DATA_VIEWED",
        )
        self.db.commit()
        return data

    def _protected_case(self, current_user: CurrentUser, case_id: uuid.UUID) -> RenovaCase:
        case = self.get_or_404(current_user.organization_id, case_id, visible_to=renova_owner_filter(current_user))
        if current_user.role not in _REVEAL_ROLES and case.assigned_user_id != current_user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not allowed to view this case's protected data.")
        return case

    def get_ine_image(self, current_user: CurrentUser, case_id: uuid.UUID, side: str) -> str | None:
        case = self._protected_case(current_user, case_id)
        token = getattr(case, _INE_COLUMNS[side])
        with self._translate_crypto_errors():
            image = reveal_secret(token) if token else None
        self.audit.record(organization_id=current_user.organization_id, actor_user_id=current_user.id,
                          entity_type=_ENTITY_TYPE, entity_id=case.id, action="RENOVA_INE_VIEWED")
        self.db.commit()
        return image

    def save_ine_image(self, current_user: CurrentUser, case_id: uuid.UUID, side: str, image: str) -> None:
        case = self._protected_case(current_user, case_id)
        match = _INE_DATA_URL.fullmatch(image)
        if not match or len(image) > 3_000_000:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use a JPEG, PNG or WebP image smaller than 2 MB.")
        try:
            raw = base64.b64decode(match.group(2), validate=True)
        except binascii.Error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid image.") from None
        signatures = {"jpeg": raw.startswith(b"\xff\xd8\xff"), "png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
                      "webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"}
        if not raw or len(raw) > _MAX_INE_BYTES or not signatures[match.group(1)]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use a JPEG, PNG or WebP image smaller than 2 MB.")
        with self._translate_crypto_errors():
            setattr(case, _INE_COLUMNS[side], encrypt_secret(image))
        self.audit.record(organization_id=current_user.organization_id, actor_user_id=current_user.id,
                          entity_type=_ENTITY_TYPE, entity_id=case.id, action="RENOVA_INE_UPDATED")
        self.db.commit()

    # --- writes ------------------------------------------------------------

    def create(
        self,
        organization_id: uuid.UUID,
        data: RenovaCaseCreate,
        actor_user_id: uuid.UUID | None = None,
        *,
        visible_to: uuid.UUID | None = None,
    ) -> RenovaCaseRead:
        self._validate_assignee(organization_id, data.assigned_user_id)
        self._check_own_assignment(visible_to, data.assigned_user_id)
        fields = data.model_dump(exclude={"nss", "credit_number"})
        encrypted = self._encrypt_inputs(
            {"nss": data.nss, "credit_number": data.credit_number}, only_set={"nss", "credit_number"}
        )
        case = self.repo.create(organization_id, created_by_user_id=actor_user_id, **fields, **encrypted)
        self._sync_legacy_final_offer(case)
        self._sync_operation_entry(case)
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
        *,
        visible_to: uuid.UUID | None = None,
    ) -> RenovaCaseRead:
        case = self.get_or_404(organization_id, case_id, visible_to=visible_to)
        provided = data.model_dump(exclude_unset=True)
        if "assigned_user_id" in provided:
            self._validate_assignee(organization_id, provided["assigned_user_id"])
            self._check_own_assignment(visible_to, provided["assigned_user_id"])
        if provided.get("archived") is True and provided.get("status", case.status) not in RENOVA_CLOSED_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only rejected or cancelled cases can be archived.")

        before_snapshot = self._audit_snapshot(case)
        before_values = {f: getattr(case, f) for f in provided if f not in _SENSITIVE_INPUTS}
        # Tracked even when this request never touched `archived`, so
        # reopening a case (moving its status away from rejected/cancelled,
        # which auto-clears the flag below) still gets its own audit row.
        before_values.setdefault("archived", case.archived)

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
        # Archiving only ever makes sense once a case has left the purchase
        # flow; reopening it (moving status away from rejected/cancelled)
        # always clears the flag too, even if this request never sent
        # `archived` at all.
        if case.status not in RENOVA_CLOSED_STATUSES and case.archived:
            case.archived = False
        self._sync_legacy_final_offer(case)
        self._sync_operation_entry(case)
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
                "has_nss": case.nss_encrypted is not None,
                "has_credit_number": case.credit_number_encrypted is not None,
            }
        )

    @staticmethod
    def _sync_legacy_final_offer(case: RenovaCase) -> None:
        """
        Keeps the legacy `final_offer` column equal to total_proposal_value
        (debt_coverage_amount + owner_cash_offer) once a case HAS a
        classified proposal, so an existing reader of that one column
        (e.g. the Kanban board's aggregate KPIs) keeps working without
        migrating field-by-field. A case that stays unclassified
        (proposal_type is None) keeps whatever `final_offer` it already
        had — never touched here, never auto-split into the new fields.
        """
        if case.proposal_type is None:
            return
        coverage = case.debt_coverage_amount or Decimal("0")
        cash = case.owner_cash_offer or Decimal("0")
        case.final_offer = coverage + cash

    @staticmethod
    def _sync_operation_entry(case: RenovaCase) -> None:
        """Start accepted legacy/new cases in operations without guessing later stages."""
        if case.operation_stage is not None:
            return
        if case.status == "accepted":
            case.operation_stage = "proposal_accepted"
        elif case.status == "purchased":
            # The old status only proves acquisition completed. Renovation is
            # the earliest honest post-purchase stage; users can reclassify it.
            case.operation_stage = "renovation"
        else:
            return
        case.operation_stage_updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _operation_snapshot(case: RenovaCase) -> dict:
        return {
            "operation_stage": case.operation_stage,
            "operation_next_action": case.operation_next_action,
            "operation_due_at": case.operation_due_at.isoformat() if case.operation_due_at else None,
            "operation_stage_updated_at": (
                case.operation_stage_updated_at.isoformat() if case.operation_stage_updated_at else None
            ),
            "status": case.status,
        }

    def _validate_assignee(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Never trusts a client-supplied advisor id — it must be a user of THIS organization. 404 (not 403) so another org's user ids can't be probed."""
        user = self.user_repo.get(user_id)
        if user is None or user.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Advisor not found.")

    @staticmethod
    def _check_own_assignment(visible_to: uuid.UUID | None, assignee_id: uuid.UUID | None) -> None:
        """A Renova-only advisor works their own cases: they can't create one for, or hand one over to, someone else (that would also hide it from them)."""
        if visible_to is not None and assignee_id != visible_to:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only assign Renova cases to yourself.")

    def _encrypt_inputs(self, values: dict[str, Any], *, only_set: set[str]) -> dict[str, str | None]:
        """{"nss": SecretStr|None, ...} -> {"nss_encrypted": ciphertext|None}. None clears; missing key is left alone."""
        out: dict[str, str | None] = {}
        for name in only_set:
            secret = values.get(name)
            column = _SENSITIVE_INPUTS[name]
            if secret is None:
                out[column] = None
                continue
            # Static message on purpose; the value is never stored unencrypted.
            with self._translate_crypto_errors():
                out[column] = encrypt_secret(secret.get_secret_value())
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
        if sensitive_changed:
            # A dedicated row so replacing / removing protected data is easy to
            # find — field NAMES only, never the old or the new value.
            record("RENOVA_SENSITIVE_DATA_CHANGED", {"sensitive_fields_changed": sensitive_changed})
        if "status" in changed:
            record("RENOVA_CASE_STATUS_CHANGED")
        if "assigned_user_id" in changed:
            record("RENOVA_CASE_ASSIGNEE_CHANGED")
        if changed & set(FINANCIAL_FIELDS):
            record("RENOVA_CASE_FINANCIALS_UPDATED")
        if "archived" in changed:
            record("RENOVA_CASE_ARCHIVED" if after["archived"] else "RENOVA_CASE_UNARCHIVED")
