from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import User
from app.models.renova_case import RenovaCase
from app.repositories.organization_repo import UserRepository
from app.schemas.enums import RENOVA_CLOSED_STATUSES
from app.schemas.retify_dashboard import (
    RetifyAdvisorPerformance,
    RetifyAttentionItem,
    RetifyDashboardPeriod,
    RetifyDashboardResponse,
    RetifyPerformanceMetrics,
)
from app.services.renova_follow_up_service import RenovaFollowUpService

_PERIOD_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
_PROPOSAL_SENT_STATUSES = {"offer_sent", "negotiating", "accepted", "purchased"}
_ACCEPTED_STATUSES = {"accepted", "purchased"}
_RETIFY_ROLES = {"owner", "admin", "renova_agent"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class RetifyDashboardService:
    """Read-only, organization-scoped performance snapshot for owners and Retify administrators."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    def read(self, organization_id: uuid.UUID, *, period: RetifyDashboardPeriod, assigned_user_id: uuid.UUID | None = None) -> RetifyDashboardResponse:
        members = self.users.list_for_organization(organization_id)
        member_by_id = {member.id: member for member in members}
        if assigned_user_id is not None and assigned_user_id not in member_by_id:
            cases: list[RenovaCase] = []
        else:
            stmt = select(RenovaCase).where(RenovaCase.organization_id == organization_id)
            if assigned_user_id is not None:
                stmt = stmt.where(RenovaCase.assigned_user_id == assigned_user_id)
            if period != "all":
                cutoff = date.today() - timedelta(days=_PERIOD_DAYS[period] - 1)
                stmt = stmt.where(RenovaCase.entry_date >= cutoff)
            cases = list(self.db.execute(stmt).scalars().all())

        summaries = RenovaFollowUpService(self.db).summaries_for_cases(organization_id, [case.id for case in cases])
        grouped: dict[uuid.UUID, list[RenovaCase]] = defaultdict(list)
        for case in cases:
            if case.assigned_user_id is not None:
                grouped[case.assigned_user_id].append(case)

        visible_members = [member for member in members if member.role in _RETIFY_ROLES or member.id in grouped]
        visible_members.sort(key=lambda member: (member.role != "owner", (member.email or "").casefold()))
        advisors = [
            RetifyAdvisorPerformance(
                user_id=member.id,
                email=member.email,
                role=member.role,
                is_active=member.is_active,
                metrics=self._metrics(grouped.get(member.id, []), summaries),
            )
            for member in visible_members
            if assigned_user_id is None or member.id == assigned_user_id
        ]
        return RetifyDashboardResponse(
            period=period,
            assigned_user_id=assigned_user_id,
            summary=self._metrics(cases, summaries),
            advisors=advisors,
            attention=self._attention(cases, summaries, member_by_id),
        )

    @staticmethod
    def _metrics(cases: list[RenovaCase], summaries: dict) -> RetifyPerformanceMetrics:
        received = len(cases)
        accepted = sum(case.status in _ACCEPTED_STATUSES for case in cases)
        return RetifyPerformanceMetrics(
            received=received,
            active=sum(not case.archived and case.status not in RENOVA_CLOSED_STATUSES for case in cases),
            closed=sum(not case.archived and case.status in RENOVA_CLOSED_STATUSES for case in cases),
            archived=sum(case.archived for case in cases),
            contacted=sum(summaries[case.id].last_call_at is not None for case in cases),
            no_answer=sum(summaries[case.id].last_result == "no_answer" for case in cases),
            follow_ups_overdue=sum(summaries[case.id].is_follow_up_overdue for case in cases),
            proposals_sent=sum(case.status in _PROPOSAL_SENT_STATUSES for case in cases),
            negotiating=sum(case.status == "negotiating" for case in cases),
            accepted=accepted,
            operations_open=sum(case.operation_stage is not None and case.operation_stage != "closed" for case in cases),
            operations_closed=sum(case.operation_stage == "closed" for case in cases),
            conversion_rate=round((accepted / received) * 100, 1) if received else 0,
        )

    @staticmethod
    def _attention(cases: list[RenovaCase], summaries: dict, members: dict[uuid.UUID, User]) -> list[RetifyAttentionItem]:
        now = datetime.now(timezone.utc)
        ranked: list[tuple[int, datetime, RetifyAttentionItem]] = []
        for case in cases:
            if case.archived or case.status in RENOVA_CLOSED_STATUSES:
                continue
            summary = summaries[case.id]
            priority: str | None = None
            reason: str | None = None
            rank = 99
            event_at = _aware(case.created_at)
            if case.operation_due_at and _aware(case.operation_due_at) < now and case.operation_stage != "closed":
                priority, reason, rank, event_at = "urgent", "La siguiente acción de la operación está vencida", 0, _aware(case.operation_due_at)
            elif summary.is_follow_up_overdue and summary.next_follow_up_at:
                priority, reason, rank, event_at = "urgent", "Seguimiento vencido", 1, _aware(summary.next_follow_up_at)
            elif case.status == "new" and summary.last_call_at is None and event_at < now - timedelta(days=2):
                priority, reason, rank = "high", "Lead nuevo sin primera llamada desde hace más de 2 días", 2
            elif summary.last_result == "no_answer" and summary.next_follow_up_at is None:
                last_call = _aware(summary.last_call_at) if summary.last_call_at else event_at
                if last_call < now - timedelta(days=3):
                    priority, reason, rank, event_at = "high", "No contestó y no tiene próximo seguimiento", 3, last_call
            elif case.status == "negotiating" and summary.next_follow_up_at is None:
                priority, reason, rank = "high", "Negociación sin siguiente seguimiento agendado", 4
            if priority and reason:
                advisor = members.get(case.assigned_user_id) if case.assigned_user_id else None
                ranked.append((rank, event_at, RetifyAttentionItem(
                    case_id=case.id,
                    owner_name=case.owner_name,
                    assigned_user_id=case.assigned_user_id,
                    advisor_email=advisor.email if advisor else None,
                    status=case.status,
                    priority=priority,
                    reason=reason,
                    next_follow_up_at=summary.next_follow_up_at,
                )))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [item for _, _, item in ranked[:20]]
