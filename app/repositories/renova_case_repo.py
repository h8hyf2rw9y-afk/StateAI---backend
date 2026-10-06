from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import case, func, or_, select

from app.core.renova_access import visible_cases_clause

from app.models.renova_case import RenovaCase
from app.repositories.base import OrgScopedRepository
from app.schemas.enums import RENOVA_CASE_STATUSES, RENOVA_CLOSED_STATUSES

# Where each status sits in the real Renova flow, as a SQL CASE -- the same
# order as RENOVA_CASE_STATUSES (app/schemas/enums.py), the single existing
# definition of that order, reused rather than duplicated. An unknown status
# (should never happen in practice; see has `else_`) sorts after every real
# one instead of raising. Built once at import time: RENOVA_CASE_STATUSES is
# a fixed tuple, not something that changes per request.
_STATUS_RANK = case(
    *((RenovaCase.status == status, rank) for rank, status in enumerate(RENOVA_CASE_STATUSES)),
    else_=len(RENOVA_CASE_STATUSES),
)


def _escape_like(value: str) -> str:
    """A user typing "%" or "_" in the search box must match those characters literally, not act as SQL wildcards."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RenovaCaseRepository(OrgScopedRepository[RenovaCase]):
    """
    Every method takes organization_id and folds it into the WHERE clause — the inherited get/create/update do the same (see OrgScopedRepository).
    The read methods also take `visible_to`: None for callers who see the whole organization, or a Renova-only advisor's user id (see app/core/renova_access.py).
    """

    model = RenovaCase

    def get_visible(
        self, organization_id: uuid.UUID, case_id: uuid.UUID, *, visible_to: uuid.UUID | None = None
    ) -> RenovaCase | None:
        stmt = select(RenovaCase).where(RenovaCase.id == case_id, *visible_cases_clause(organization_id, visible_to))
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        q: str | None = None,
        status: str | None = None,
        assigned_user_id: uuid.UUID | None = None,
        archived: bool | None = None,
        bucket: str | None = None,
        limit: int = 50,
        offset: int = 0,
        visible_to: uuid.UUID | None = None,
    ) -> list[RenovaCase]:
        stmt = select(RenovaCase).where(*visible_cases_clause(organization_id, visible_to))
        if bucket == "active":
            stmt = stmt.where(RenovaCase.archived.is_(False), RenovaCase.status.notin_(RENOVA_CLOSED_STATUSES))
        elif bucket == "closed":
            stmt = stmt.where(RenovaCase.archived.is_(False), RenovaCase.status.in_(RENOVA_CLOSED_STATUSES))
        elif bucket == "archived":
            stmt = stmt.where(RenovaCase.archived.is_(True))
        else:
            # No bucket requested -> exactly the original behavior (callers
            # that predate `bucket` keep getting the same results): not
            # specified hides archived cases by default, the caller has to
            # explicitly ask for archived=true to see them.
            stmt = stmt.where(RenovaCase.archived == (False if archived is None else archived))
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
        # Grouped by where each case sits in the Renova flow (not by entry
        # date -- see _STATUS_RANK's docstring); newest-created first within
        # the same status; `id` is the final, stable tiebreaker so two rows
        # with the same status and the same created_at (same request, or a
        # seed script) always come back in the same order across pages.
        # Applied BEFORE limit/offset so pagination never splits a status
        # group inconsistently across requests.
        stmt = (
            stmt.order_by(_STATUS_RANK.asc(), RenovaCase.created_at.desc(), RenovaCase.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def counts(self, organization_id: uuid.UUID, *, visible_to: uuid.UUID | None = None) -> dict[str, int]:
        """
        One grouped query for the three Leads -> Renova tabs' counters: never
        fetch (or filter client-side) every case in an organization that
        might have hundreds just to show how many are in each bucket.
        """
        stmt = (
            select(RenovaCase.status, RenovaCase.archived, func.count())
            .where(*visible_cases_clause(organization_id, visible_to))
            .group_by(RenovaCase.status, RenovaCase.archived)
        )
        active = closed = rejected = cancelled = archived_total = 0
        for status, is_archived, count in self.db.execute(stmt).all():
            if is_archived:
                archived_total += count
                continue
            if status in RENOVA_CLOSED_STATUSES:
                closed += count
                if status == "rejected":
                    rejected += count
                elif status == "cancelled":
                    cancelled += count
            else:
                active += count
        return {
            "active": active,
            "closed": closed,
            "rejected": rejected,
            "cancelled": cancelled,
            "archived": archived_total,
        }

    def list_for_pipeline(
        self, organization_id: uuid.UUID, statuses: Sequence[str], *, visible_to: uuid.UUID | None = None
    ) -> list[RenovaCase]:
        """
        Every case in one of `statuses` for the board — deliberately
        unpaginated: the Kanban board must never silently hide a case behind
        a page boundary, and an organization's active Renova pipeline is
        realistically small.
        """
        stmt = (
            select(RenovaCase)
            .where(*visible_cases_clause(organization_id, visible_to), RenovaCase.status.in_(statuses))
            .order_by(RenovaCase.entry_date.desc(), RenovaCase.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_operations(
        self,
        organization_id: uuid.UUID,
        stages: Sequence[str],
        *,
        visible_to: uuid.UUID | None = None,
    ) -> list[RenovaCase]:
        """Every live post-acceptance operation, grouped in stage order by the service."""
        stage_rank = case(
            *((RenovaCase.operation_stage == stage, rank) for rank, stage in enumerate(stages)),
            else_=len(stages),
        )
        stmt = (
            select(RenovaCase)
            .where(
                *visible_cases_clause(organization_id, visible_to),
                RenovaCase.archived.is_(False),
                RenovaCase.status.in_(("accepted", "purchased")),
                RenovaCase.operation_stage.in_(stages),
            )
            .order_by(
                stage_rank.asc(),
                RenovaCase.operation_due_at.asc().nulls_last(),
                RenovaCase.operation_stage_updated_at.asc().nulls_last(),
                RenovaCase.id.asc(),
            )
        )
        return list(self.db.execute(stmt).scalars().all())
