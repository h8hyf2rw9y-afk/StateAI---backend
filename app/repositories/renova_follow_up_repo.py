import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.renova_follow_up import RenovaFollowUpActivity
from app.repositories.base import OrgScopedRepository


class RenovaFollowUpRepository(OrgScopedRepository[RenovaFollowUpActivity]):
    model = RenovaFollowUpActivity

    def list_for_case(self, organization_id: uuid.UUID, case_id: uuid.UUID) -> list[RenovaFollowUpActivity]:
        stmt = (
            select(RenovaFollowUpActivity)
            .where(
                RenovaFollowUpActivity.organization_id == organization_id,
                RenovaFollowUpActivity.renova_case_id == case_id,
            )
            .order_by(RenovaFollowUpActivity.occurred_at.desc(), RenovaFollowUpActivity.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_cases(
        self, organization_id: uuid.UUID, case_ids: Sequence[uuid.UUID]
    ) -> list[RenovaFollowUpActivity]:
        if not case_ids:
            return []
        stmt = (
            select(RenovaFollowUpActivity)
            .where(
                RenovaFollowUpActivity.organization_id == organization_id,
                RenovaFollowUpActivity.renova_case_id.in_(case_ids),
            )
            .order_by(RenovaFollowUpActivity.occurred_at.desc(), RenovaFollowUpActivity.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def next_attempt_number(self, organization_id: uuid.UUID, case_id: uuid.UUID) -> int:
        stmt = select(func.max(RenovaFollowUpActivity.attempt_number)).where(
            RenovaFollowUpActivity.organization_id == organization_id,
            RenovaFollowUpActivity.renova_case_id == case_id,
            RenovaFollowUpActivity.activity_type == "call",
        )
        return int(self.db.execute(stmt).scalar_one_or_none() or 0) + 1
