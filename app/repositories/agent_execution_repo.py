from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.models.agent_execution import AgentExecution
from app.repositories.base import OrgScopedRepository


class AgentExecutionRepository(OrgScopedRepository[AgentExecution]):
    model = AgentExecution

    def list(
        self,
        organization_id: uuid.UUID,
        *,
        contact_id: uuid.UUID | None = None,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentExecution]:
        stmt = select(AgentExecution).where(AgentExecution.organization_id == organization_id)
        if contact_id is not None:
            stmt = stmt.where(AgentExecution.contact_id == contact_id)
        if agent_name is not None:
            stmt = stmt.where(AgentExecution.agent_name == agent_name)
        if status is not None:
            # Added for the "latest valid result per (contact, agent)" lookup
            # (AgentExecutionService.get_latest_succeeded) — a failed attempt
            # must never shadow the last real success in that lookup.
            stmt = stmt.where(AgentExecution.status == status)
        stmt = stmt.order_by(AgentExecution.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def get_by_idempotency_key(self, organization_id: uuid.UUID, idempotency_key: str) -> AgentExecution | None:
        stmt = select(AgentExecution).where(
            AgentExecution.organization_id == organization_id,
            AgentExecution.idempotency_key == idempotency_key,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_active(
        self, organization_id: uuid.UUID, *, contact_id: uuid.UUID, agent_name: str
    ) -> AgentExecution | None:
        stmt = (
            select(AgentExecution)
            .where(
                AgentExecution.organization_id == organization_id,
                AgentExecution.contact_id == contact_id,
                AgentExecution.agent_name == agent_name,
                AgentExecution.status.in_(("queued", "running")),
            )
            .order_by(AgentExecution.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def count_since(
        self,
        organization_id: uuid.UUID,
        *,
        since: datetime,
        user_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        agent_name: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(AgentExecution).where(
            AgentExecution.organization_id == organization_id,
            AgentExecution.created_at >= since,
        )
        if user_id is not None:
            stmt = stmt.where(AgentExecution.user_id == user_id)
        if contact_id is not None:
            stmt = stmt.where(AgentExecution.contact_id == contact_id)
        if agent_name is not None:
            stmt = stmt.where(AgentExecution.agent_name == agent_name)
        return int(self.db.execute(stmt).scalar_one())
