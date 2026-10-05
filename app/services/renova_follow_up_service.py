import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.renova_follow_up import RenovaFollowUpActivity
from app.repositories.renova_case_repo import RenovaCaseRepository
from app.repositories.renova_follow_up_repo import RenovaFollowUpRepository
from app.schemas.renova_follow_up import (
    RenovaFollowUpActivityCreate,
    RenovaFollowUpActivityRead,
    RenovaFollowUpActivityUpdate,
    RenovaFollowUpDetail,
    RenovaFollowUpSummary,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class RenovaFollowUpService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RenovaFollowUpRepository(db)
        self.case_repo = RenovaCaseRepository(db)

    @staticmethod
    def summarize(activities: list[RenovaFollowUpActivity]) -> RenovaFollowUpSummary:
        calls = [item for item in activities if item.activity_type == "call"]
        latest_call = max(calls, key=lambda item: (_aware(item.occurred_at), _aware(item.created_at))) if calls else None
        # The most recent operational event owns the next action. A later call
        # without a new date intentionally clears an older reminder instead of
        # leaving a stale "overdue" badge forever.
        latest_event = max(
            activities, key=lambda item: (_aware(item.occurred_at), _aware(item.created_at))
        ) if activities else None
        next_at = latest_event.next_follow_up_at if latest_event else None
        attempt_count = max((item.attempt_number or 0 for item in calls), default=0)
        result = latest_call.result if latest_call else None
        states = {
            "no_answer": "attempted_no_answer",
            "interested": "contacted_interested",
            "callback_requested": "callback_requested",
            "not_interested": "not_interested",
            "other": "contacted",
        }
        return RenovaFollowUpSummary(
            last_call_activity_id=latest_call.id if latest_call else None,
            last_call_at=latest_call.occurred_at if latest_call else None,
            last_result=result,
            contact_attempt_count=attempt_count,
            next_follow_up_at=next_at,
            is_follow_up_overdue=bool(next_at and _aware(next_at) < datetime.now(timezone.utc)),
            contact_state=states.get(result, "never_contacted"),
            note_preview=(latest_call.notes[:180] if latest_call and latest_call.notes else None),
        )

    def summaries_for_cases(
        self, organization_id: uuid.UUID, case_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, RenovaFollowUpSummary]:
        grouped: dict[uuid.UUID, list[RenovaFollowUpActivity]] = defaultdict(list)
        for activity in self.repo.list_for_cases(organization_id, case_ids):
            grouped[activity.renova_case_id].append(activity)
        return {case_id: self.summarize(grouped[case_id]) for case_id in case_ids}

    def detail(self, organization_id: uuid.UUID, case_id: uuid.UUID) -> RenovaFollowUpDetail:
        self._case_or_404(organization_id, case_id)
        activities = self.repo.list_for_case(organization_id, case_id)
        return RenovaFollowUpDetail(
            summary=self.summarize(activities),
            activities=[RenovaFollowUpActivityRead.model_validate(item) for item in activities],
        )

    def create(
        self,
        organization_id: uuid.UUID,
        case_id: uuid.UUID,
        data: RenovaFollowUpActivityCreate,
        *,
        actor_user_id: uuid.UUID,
    ) -> RenovaFollowUpDetail:
        self._case_or_404(organization_id, case_id)
        fields = data.model_dump()
        if data.activity_type == "call" and data.attempt_number is None:
            fields["attempt_number"] = self.repo.next_attempt_number(organization_id, case_id)
        self.repo.create(
            organization_id,
            renova_case_id=case_id,
            actor_user_id=actor_user_id,
            **fields,
        )
        self.db.commit()
        return self.detail(organization_id, case_id)

    def update(
        self,
        organization_id: uuid.UUID,
        case_id: uuid.UUID,
        activity_id: uuid.UUID,
        data: RenovaFollowUpActivityUpdate,
    ) -> RenovaFollowUpDetail:
        self._case_or_404(organization_id, case_id)
        activity = self.repo.get(organization_id, activity_id)
        if activity is None or activity.renova_case_id != case_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Renova follow-up activity not found.")
        fields = data.model_dump(exclude_unset=True)
        if activity.activity_type == "follow_up" and ("result" in fields or "attempt_number" in fields):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A scheduled follow-up cannot carry call fields.")
        if activity.activity_type == "call" and fields.get("result", activity.result) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A call must keep a result.")
        if activity.activity_type == "follow_up" and fields.get("next_follow_up_at", activity.next_follow_up_at) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A scheduled follow-up must keep its date.")
        for name, value in fields.items():
            setattr(activity, name, value)
        self.db.flush()
        self.db.commit()
        return self.detail(organization_id, case_id)

    def _case_or_404(self, organization_id: uuid.UUID, case_id: uuid.UUID):
        case = self.case_repo.get(organization_id, case_id)
        if case is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Renova case not found.")
        return case
