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
