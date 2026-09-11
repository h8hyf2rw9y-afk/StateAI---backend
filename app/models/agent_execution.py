import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin

_JSONVariant = JSONB().with_variant(JSON(), "sqlite")


class AgentExecution(Base, UUIDPKMixin, CreatedAtMixin):
    """
    Observability/persistence for one AI agent run — "what did the AI
    recommend, for whom, when, and did anyone act on it." Written by
    app/api/routes/ai.py (not by app/ai/gateway.py itself — the Gateway's
    own docstring states it never touches the database; this table's writes
    live at the route layer instead, right after/around the existing
    AIGateway.run() call, so that stable contract stays intact). See
    app/services/agent_execution_service.py.

    Purely additive infrastructure: agents remain read-only/advisory. This
    table records what an agent said, never lets it act — see the project's
    architectural rule that AI must not autonomously modify CRM data.
    """

    __tablename__ = "agent_executions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(nullable=False)  # matches AgentDescriptor.agent_id, e.g. "lead_intelligence"
    agent_version: Mapped[str] = mapped_column(nullable=False)

    # SET NULL (not CASCADE): deleting the contact/user later shouldn't erase
    # the historical fact that an AI execution happened — same reasoning as
    # Activity's optional foreign keys.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Holds {"context_fingerprint": {...}} — a small, deterministic summary
    # (per-entity counts and latest-modified timestamps) of the contact's
    # CRM state at the moment this execution succeeded, NOT a duplicate of
    # the LeadContext itself (that stays reconstructible on demand via
    # GET /ai/lead-context/{contact_id}; see app/ai/lead_context_tool.py).
    # Used by GET /ai/agent-executions/latest to decide whether a stored
    # result is stale relative to the contact's current data — see
    # LeadContextService.compute_context_fingerprint. Still nullable: a
    # failed execution never gets one, and older rows written before this
    # existed have none either (treated as "not stale" by the reader — see
    # that route's own comment).
    input_snapshot: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    # The agent's own structured Result schema, dumped via .model_dump(mode="json").
    # On a failed execution this holds {"error": "<exception class>", "message": "..."}
    # instead — always populated, never NULL, so "what happened" is always answerable.
    output: Mapped[dict] = mapped_column(_JSONVariant, nullable=False)

    # Soft enum: succeeded | failed.
    status: Mapped[str] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(nullable=False)  # LLMProvider.provider_name, e.g. "ollama"/"anthropic"/"fake"
    model: Mapped[str] = mapped_column(nullable=False)  # LLMProvider.model_name
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)

    # Soft enum: acted_on | dismissed. NULL means no human has recorded a
    # reaction yet. Set via PATCH /ai/agent-executions/{id} — see
    # app/api/routes/agent_executions.py.
    human_action: Mapped[str | None] = mapped_column(nullable=True)
    human_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_executions_organization_id", "organization_id"),
        Index("ix_agent_executions_contact_id", "contact_id"),
        Index("ix_agent_executions_org_agent", "organization_id", "agent_name"),
        Index("ix_agent_executions_org_created_at", "organization_id", "created_at"),
    )
