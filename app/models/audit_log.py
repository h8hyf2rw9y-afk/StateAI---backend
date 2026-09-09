import uuid

from sqlalchemy import JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPKMixin

# JSONB on Postgres (indexable, efficient); plain JSON on SQLite (what the
# test suite runs on — see tests/conftest.py) since JSONB has no SQLite
# equivalent. Same pattern used by app/models/agent_execution.py.
_JSONVariant = JSONB().with_variant(JSON(), "sqlite")


class AuditLog(Base, UUIDPKMixin, CreatedAtMixin):
    """
    "Who changed what, when" for CRM data — distinct from Activity (which
    records a contact-facing event like a call or viewing) and from
    AgentExecution (which records an AI recommendation). An audit log row is
    never updated or deleted through the app; CreatedAtMixin (not
    TimestampMixin) reflects that append-only intent.

    Written exclusively through app/services/audit_service.py's
    AuditService.record(...) — never assembled ad hoc in a route or another
    service, so every future module logs the same shape the same way. See
    that file for the actual write path and for why organization_id/
    actor_user_id always come from CurrentUser, never client input.
    """

    __tablename__ = "audit_logs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, not CASCADE: a user account being deleted later must never
    # erase the historical fact that *some* action happened — same
    # reasoning as Activity.created_by_user_id.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Freeform, not a soft-enum Literal: unlike a CRM domain field (whose
    # value set is small and known up front), every future module adds its
    # own entity_type/action pair, and this table must accept that without
    # a code change here. Convention (not enforced): entity_type is the
    # lowercase singular table/model name ("contact", "task", ...); action
    # is "<ENTITY>_<VERB>" upper snake case ("CONTACT_CREATED").
    entity_type: Mapped[str] = mapped_column(nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(nullable=False)

    # Snapshots of the entity's own Read-schema shape, dumped via
    # `SomeReadSchema.model_validate(obj).model_dump(mode="json")` at the
    # call site — never the raw ORM `__dict__` — so a field that
    # legitimately shouldn't be here (there are none today, but a future
    # entity might add one) is excluded the same way it's already excluded
    # from that entity's API response, not by a second exclusion list here.
    # NULL before_data means "didn't exist yet" (creation); NULL after_data
    # means "no longer exists" (deletion).
    before_data: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(_JSONVariant, nullable=True)

    __table_args__ = (
        Index("ix_audit_logs_organization_id", "organization_id"),
        Index("ix_audit_logs_org_entity", "organization_id", "entity_type", "entity_id"),
        Index("ix_audit_logs_org_created_at", "organization_id", "created_at"),
        Index("ix_audit_logs_actor_user_id", "actor_user_id"),
    )
