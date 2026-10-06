from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.renova_case import RenovaCase
from app.repositories.organization_repo import UserRepository
from app.schemas.enums import RENOVA_CLOSED_STATUSES
from app.schemas.organization_member import (
    MemberRenovaCaseCounts,
    OrganizationMemberRead,
    OrganizationMemberUpdate,
)
from app.schemas.user import CurrentUser
from app.services.audit_service import AuditService

_ENTITY_TYPE = "user"


class OrganizationMemberService:
    """
    The owner/admin view of who is in the organization (routes gate it with
    require_role("owner", "admin")). Deactivating never deletes anything: the
    `users` row and every case it owns stay, and get_current_org_user simply
    refuses that account until it's reactivated.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    def list(self, current_user: CurrentUser) -> list[OrganizationMemberRead]:
        members = sorted(
            self.user_repo.list_for_organization(current_user.organization_id),
            key=lambda user: (user.role != "owner", (user.email or "").casefold()),
        )
        counts = self._renova_case_counts(current_user.organization_id)
        return [
            OrganizationMemberRead.model_validate(member).model_copy(
                update={"renova_cases": counts.get(member.id, MemberRenovaCaseCounts())}
            )
            for member in members
        ]

    def update(
        self, current_user: CurrentUser, member_id: uuid.UUID, data: OrganizationMemberUpdate
    ) -> OrganizationMemberRead:
        member = self.user_repo.get(member_id)
        if member is None or member.organization_id != current_user.organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
        if member.id == current_user.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "You can't deactivate your own account.")
        if member.role == "owner":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "The organization owner can't be deactivated.")
        if member.role == "admin" and current_user.role != "owner":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change another admin's access.")

        if member.is_active != data.is_active:
            member.is_active = data.is_active
            member.deactivated_at = None if data.is_active else datetime.now(timezone.utc)
            self.db.flush()
            self.audit.record(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                entity_type=_ENTITY_TYPE,
                entity_id=member.id,
                action="USER_REACTIVATED" if data.is_active else "USER_DEACTIVATED",
                after={"email": member.email, "role": member.role},
            )
            self.db.commit()
            self.db.refresh(member)
        counts = self._renova_case_counts(current_user.organization_id)
        return OrganizationMemberRead.model_validate(member).model_copy(
            update={"renova_cases": counts.get(member.id, MemberRenovaCaseCounts())}
        )

    def _renova_case_counts(self, organization_id: uuid.UUID) -> dict[uuid.UUID, MemberRenovaCaseCounts]:
        """One grouped query for every member at once — never a count per row."""
        stmt = (
            select(RenovaCase.assigned_user_id, RenovaCase.status, RenovaCase.archived, func.count())
            .where(RenovaCase.organization_id == organization_id)
            .group_by(RenovaCase.assigned_user_id, RenovaCase.status, RenovaCase.archived)
        )
        totals: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"active": 0, "closed": 0, "archived": 0})
        for assignee, case_status, archived, count in self.db.execute(stmt).all():
            if assignee is None:
                continue
            bucket = "archived" if archived else "closed" if case_status in RENOVA_CLOSED_STATUSES else "active"
            totals[assignee][bucket] += count
        return {user_id: MemberRenovaCaseCounts(**values) for user_id, values in totals.items()}
