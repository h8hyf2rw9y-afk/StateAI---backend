from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.agent_execution import AgentExecution
from app.repositories.agent_execution_repo import AgentExecutionRepository
from app.schemas.enums import HumanActionStatus


class AgentExecutionService:
    """
    Persists "what did the AI recommend, for whom, when, did it work" — see
    app/models/agent_execution.py. Written from app/api/routes/ai.py, right
    around the existing AIGateway.run() call, NOT from inside AIGateway
    itself: the Gateway's own docstring states it never touches the
    database, and that stays true — this service is the route's concern,
    the same way HTTP-status mapping for LLM errors already is.

    Purely observability: nothing here lets an agent write CRM data, and
    `record_*` never raises on its own account for a bad outcome — a failed
    AI call still needs to be logged, not swallowed by a logging failure.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AgentExecutionRepository(db)

    def record_success(
        self,
        *,
        organization_id: uuid.UUID,
        agent_name: str,
        agent_version: str,
        contact_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        provider: str,
        model: str,
        duration_ms: int,
        result: BaseModel,
        context_fingerprint: dict | None = None,
    ) -> AgentExecution:
        execution = self.repo.create(
            organization_id,
            agent_name=agent_name,
            agent_version=agent_version,
            contact_id=contact_id,
            user_id=user_id,
            # See app/models/agent_execution.py — this column now holds the
            # deterministic context fingerprint that was current at execution
            # time (not a duplicate of the CRM data itself), used later to
            # decide whether a stored result is stale. None for a contact-less
            # execution (can't happen for the three agents today, but the
            # field stays optional for forward compatibility).
            input_snapshot={"context_fingerprint": context_fingerprint} if context_fingerprint is not None else None,
            output=result.model_dump(mode="json"),
            status="succeeded",
            provider=provider,
            model=model,
            duration_ms=duration_ms,
        )
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def record_failure(
        self,
        *,
        organization_id: uuid.UUID,
        agent_name: str,
        agent_version: str,
        contact_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        provider: str,
        model: str,
        duration_ms: int,
        error: Exception,
    ) -> AgentExecution:
        execution = self.repo.create(
            organization_id,
            agent_name=agent_name,
            agent_version=agent_version,
            contact_id=contact_id,
            user_id=user_id,
            input_snapshot=None,
            output={"error": type(error).__name__, "message": str(error)},
            status="failed",
            provider=provider,
            model=model,
            duration_ms=duration_ms,
        )
        self.db.commit()
        self.db.refresh(execution)
        return execution

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
        return self.repo.list(
            organization_id, contact_id=contact_id, agent_name=agent_name, status=status, limit=limit, offset=offset
        )

    def get_latest_succeeded(
        self, organization_id: uuid.UUID, *, contact_id: uuid.UUID, agent_name: str
    ) -> AgentExecution | None:
        """
        "What did we last successfully tell this advisor about this contact
        with this agent?" — the read path behind restoring a client's
        previous analysis on switch (see GET /ai/agent-executions/latest).
        Filtered to status="succeeded" so a since-superseded failed retry
        never shadows the last real result; ordered newest-first by the
        repo, so limit=1 is exactly "the latest relevant one" even when
        there are many historical executions.
        """
        results = self.repo.list(organization_id, contact_id=contact_id, agent_name=agent_name, status="succeeded", limit=1)
        return results[0] if results else None

    def get_or_404(self, organization_id: uuid.UUID, execution_id: uuid.UUID) -> AgentExecution:
        execution = self.repo.get(organization_id, execution_id)
        if execution is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent execution not found.")
        return execution

    def set_human_action(
        self, organization_id: uuid.UUID, execution_id: uuid.UUID, human_action: HumanActionStatus
    ) -> AgentExecution:
        execution = self.get_or_404(organization_id, execution_id)
        execution.human_action = human_action
        execution.human_action_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(execution)
        return execution
