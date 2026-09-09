from __future__ import annotations

import uuid

from sqlalchemy import select

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
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentExecution]:
        stmt = select(AgentExecution).where(AgentExecution.organization_id == organization_id)
        if contact_id is not None:
            stmt = stmt.where(AgentExecution.contact_id == contact_id)
        if agent_name is not None:
            stmt = stmt.where(AgentExecution.agent_name == agent_name)
        stmt = stmt.order_by(AgentExecution.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())
