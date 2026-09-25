from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import or_, select

from app.models.renova_case import RenovaCase
from app.repositories.base import OrgScopedRepository


def _escape_like(value: str) -> str:
    """A user typing "%" or "_" in the search box must match those characters literally, not act as SQL wildcards."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RenovaCaseRepository(OrgScopedRepository[RenovaCase]):
    """Every method takes organization_id and folds it into the WHERE clause — the inherited get/create/update do the same (see OrgScopedRepository)."""

    model = RenovaCase

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        q: str | None = None,
        status: str | None = None,
        assigned_user_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RenovaCase]:
        stmt = select(RenovaCase).where(RenovaCase.organization_id == organization_id)
        if status is not None:
            stmt = stmt.where(RenovaCase.status == status)
        if assigned_user_id is not None:
            stmt = stmt.where(RenovaCase.assigned_user_id == assigned_user_id)
        term = (q or "").strip()
        if term:
            pattern = f"%{_escape_like(term)}%"
            stmt = stmt.where(
                or_(
                    RenovaCase.owner_name.ilike(pattern, escape="\\"),
                    RenovaCase.owner_phone.ilike(pattern, escape="\\"),
                )
            )
        # Newest intake first; created_at breaks ties between cases logged the same day.
        stmt = stmt.order_by(RenovaCase.entry_date.desc(), RenovaCase.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def list_for_pipeline(self, organization_id: uuid.UUID, statuses: Sequence[str]) -> list[RenovaCase]:
        """
        Every case in one of `statuses` for the board — deliberately
        unpaginated: the Kanban board must never silently hide a case behind
        a page boundary, and an organization's active Renova pipeline is
        realistically small.
        """
        stmt = (
            select(RenovaCase)
            .where(RenovaCase.organization_id == organization_id, RenovaCase.status.in_(statuses))
            .order_by(RenovaCase.entry_date.desc(), RenovaCase.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
