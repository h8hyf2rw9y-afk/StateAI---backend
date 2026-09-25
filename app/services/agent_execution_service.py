from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_execution import AgentExecution
from app.repositories.agent_execution_repo import AgentExecutionRepository
from app.repositories.contact_repo import ContactRepository
from app.schemas.enums import HumanActionStatus


@dataclass(frozen=True)
class BeginExecutionResult:
    kind: Literal["started", "in_progress", "replayed"]
    execution: AgentExecution


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class AgentExecutionService:
    """
    Persists "what did the AI recommend, for whom, when, did it work" — see
    app/models/agent_execution.py. Written from app/api/routes/ai.py, right
    around the existing AIGateway.run() call, NOT from inside AIGateway
    itself: the Gateway's own docstring states it never touches the
    database, and that stays true — this service is the route's concern,
    the same way HTTP-status mapping for LLM errors already is.

    The row is now reserved before the provider call. That makes the
    database the source of truth for single-flight and idempotency instead
    of relying on one Python process or a disabled frontend button.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AgentExecutionRepository(db)

    def begin(
        self,
        *,
        organization_id: uuid.UUID,
        agent_name: str,
        agent_version: str,
        contact_id: uuid.UUID,
        user_id: uuid.UUID,
        provider: str,
        model: str,
        idempotency_key: str | None,
    ) -> BeginExecutionResult:
        if ContactRepository(self.db).get(organization_id, contact_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found.")

        if idempotency_key:
            existing = self.repo.get_by_idempotency_key(organization_id, idempotency_key)
            if existing is not None:
                return self._resolve_idempotent_execution(
                    existing,
                    contact_id=contact_id,
                    agent_name=agent_name,
                    user_id=user_id,
                )

        active = self.repo.get_active(organization_id, contact_id=contact_id, agent_name=agent_name)
        if active is not None:
            return BeginExecutionResult("in_progress", active)

        now = datetime.now(timezone.utc)
        latest = self.get_latest_succeeded(organization_id, contact_id=contact_id, agent_name=agent_name)
        cooldown = settings.ai_agent_cooldown_seconds
        if cooldown > 0 and latest is not None:
            retry_after = max(0, int((_utc(latest.created_at) + timedelta(seconds=cooldown) - now).total_seconds()) + 1)
            if retry_after > 0:
                self._raise_limit(
                    code="AI_COOLDOWN",
                    message="This analysis was refreshed recently. Please wait before running it again.",
                    retry_after=retry_after,
                )

        self._check_rate_limits(organization_id, user_id=user_id, contact_id=contact_id, agent_name=agent_name, now=now)

        try:
            execution = self.repo.create(
                organization_id,
                agent_name=agent_name,
                agent_version=agent_version,
                contact_id=contact_id,
                user_id=user_id,
                input_snapshot=None,
                output={"state": "running"},
                status="running",
                provider=provider,
                model=model,
                duration_ms=None,
                completed_at=None,
                idempotency_key=idempotency_key,
            )
            self.db.commit()
            self.db.refresh(execution)
            return BeginExecutionResult("started", execution)
        except IntegrityError:
            # A second process may have passed the read checks at the same
            # instant. The partial unique indexes are the final authority.
            self.db.rollback()
            if idempotency_key:
                existing = self.repo.get_by_idempotency_key(organization_id, idempotency_key)
                if existing is not None:
                    return self._resolve_idempotent_execution(
                        existing,
                        contact_id=contact_id,
                        agent_name=agent_name,
                        user_id=user_id,
                    )
            active = self.repo.get_active(organization_id, contact_id=contact_id, agent_name=agent_name)
            if active is not None:
                return BeginExecutionResult("in_progress", active)
            raise

    def complete_success(
        self,
        *,
        execution: AgentExecution,
        duration_ms: int,
        result: BaseModel,
        context_fingerprint: dict | None,
    ) -> AgentExecution:
        execution.input_snapshot = (
            {"context_fingerprint": context_fingerprint} if context_fingerprint is not None else None
        )
        execution.output = result.model_dump(mode="json")
        execution.status = "succeeded"
        execution.duration_ms = duration_ms
        execution.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def complete_failure(
        self,
        *,
        execution: AgentExecution,
        duration_ms: int,
        error: Exception,
    ) -> AgentExecution:
        execution.input_snapshot = None
        execution.output = {"error": type(error).__name__, "message": str(error)}
        execution.status = "failed"
        execution.duration_ms = duration_ms
        execution.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def _check_rate_limits(
        self,
        organization_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        agent_name: str,
        now: datetime,
    ) -> None:
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        checks = (
            (
                settings.ai_user_rate_limit_per_minute,
                self.repo.count_since(organization_id, since=minute_ago, user_id=user_id),
                60,
                "AI_USER_RATE_LIMIT",
            ),
            (
                settings.ai_organization_rate_limit_per_minute,
                self.repo.count_since(organization_id, since=minute_ago),
                60,
                "AI_ORGANIZATION_RATE_LIMIT",
            ),
            (
                settings.ai_contact_agent_rate_limit_per_hour,
                self.repo.count_since(
                    organization_id,
                    since=hour_ago,
                    contact_id=contact_id,
                    agent_name=agent_name,
                ),
                3600,
                "AI_CONTACT_AGENT_RATE_LIMIT",
            ),
        )
        for limit, current, retry_after, code in checks:
            if limit > 0 and current >= limit:
                self._raise_limit(
                    code=code,
                    message="The AI analysis limit has been reached. Please try again later.",
                    retry_after=retry_after,
                )

    @staticmethod
    def _raise_limit(*, code: str, message: str, retry_after: int) -> None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"code": code, "message": message, "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    @staticmethod
    def _resolve_idempotent_execution(
        execution: AgentExecution,
        *,
        contact_id: uuid.UUID,
        agent_name: str,
        user_id: uuid.UUID,
    ) -> BeginExecutionResult:
        if (
            execution.contact_id != contact_id
            or execution.agent_name != agent_name
            or execution.user_id != user_id
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": "IDEMPOTENCY_KEY_REUSED",
                    "message": "This idempotency key was already used for a different analysis request.",
                },
            )
        if execution.status == "succeeded":
            return BeginExecutionResult("replayed", execution)
        if execution.status in {"queued", "running"}:
            return BeginExecutionResult("in_progress", execution)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "IDEMPOTENT_EXECUTION_FAILED", "message": "This request already failed. Start a new analysis."},
        )

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
