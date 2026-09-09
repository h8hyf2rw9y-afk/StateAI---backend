import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class CalendarConnection(Base, UUIDPKMixin, TimestampMixin):
    """
    Records ONE user's intent to sync PropPilot Appointments with an
    external calendar (Google/Apple/Notion) — metadata only.

    Deliberately has NO access_token/refresh_token columns. Storing a real
    OAuth token requires encryption at rest (e.g. pgcrypto, envelope
    encryption via a KMS, or app-level encryption with a securely-managed
    key) and none of that infrastructure exists in this codebase yet — no
    `cryptography` dependency, no key management. Adding a plaintext token
    column instead would be a real credential-exposure risk sitting in the
    database, so per this project's own security rules that column is
    intentionally omitted rather than implemented insecurely. See the
    README's Calendar Integration Architecture section.

    `status` never actually reaches "connected" today — there is no OAuth
    flow to get it there (see app/integrations/calendar/). The column
    exists now so the eventual OAuth implementation is a data update, not a
    schema change.
    """

    __tablename__ = "calendar_connections"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Soft enum: calendar_provider_name (google/apple/notion).
    provider: Mapped[str] = mapped_column(nullable=False)
    # An identifying label only (e.g. the connected account's email) — never a secret.
    external_account_id: Mapped[str | None] = mapped_column(nullable=True)
    # Comma-separated OAuth scope names the connection would request/hold —
    # harmless to store (it's not a credential, just what was asked for).
    scopes: Mapped[str | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft enum: pending | connected | expired | error | disconnected.
    status: Mapped[str] = mapped_column(nullable=False, default="pending")

    __table_args__ = (
        Index("ix_calendar_connections_organization_id", "organization_id"),
        Index("ix_calendar_connections_user_id", "user_id"),
        # One connection per (user, provider) — reconnecting replaces the
        # existing row's status rather than accumulating duplicates.
        UniqueConstraint("user_id", "provider", name="uq_calendar_connections_user_provider"),
    )
