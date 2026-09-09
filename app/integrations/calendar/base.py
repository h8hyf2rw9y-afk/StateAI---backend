"""
The CalendarProvider interface — what a future Google/Apple/Notion
integration would implement. This module defines the shape ONLY; no
subclass here actually talks to any external API (see google.py/apple.py/
notion.py, each a stub that raises CalendarIntegrationNotImplementedError).

Design principle this whole package exists to protect: an Appointment row
in PropPilot's own database (app/models/appointment.py) is always the
source of truth. A CalendarProvider is a synchronization *target* —
something PropPilot's Appointment gets mirrored to — never the other way
around, and never something a route or service depends on to function.
Nothing in this codebase currently calls any of these methods.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class CalendarIntegrationNotImplementedError(NotImplementedError):
    """Raised by every stub in this package — see google.py/apple.py/notion.py. Distinguishes "not implemented yet" from a genuine NotImplementedError bug elsewhere."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            f"{provider} calendar integration is not implemented yet — see the README's "
            "Calendar Integration Architecture section. This is architecture scaffolding only."
        )


@dataclass(frozen=True)
class CalendarEventInput:
    """What PropPilot would send to create/update an external event — mirrors the fields on Appointment that matter to a calendar, not the whole row (no organization_id, no internal ids beyond what's needed to round-trip)."""

    title: str
    start_at: datetime
    end_at: datetime
    description: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class CalendarEvent:
    """What an external provider hands back — enough to store as Appointment.external_calendar_event_id and to reconcile on a future sync."""

    external_event_id: str
    title: str
    start_at: datetime
    end_at: datetime


class CalendarProvider(Protocol):
    """
    One implementation per external provider (google.py/apple.py/notion.py).
    All five operations are conceptual today — every concrete class in this
    package raises CalendarIntegrationNotImplementedError instead of
    pretending to call a real API. A real implementation would take a
    CalendarConnection (app/models/calendar_connection.py) — which, note,
    has no access_token/refresh_token columns yet; see that model's
    docstring for why.
    """

    def create_event(self, connection_id: uuid.UUID, event: CalendarEventInput) -> CalendarEvent: ...

    def update_event(self, connection_id: uuid.UUID, external_event_id: str, event: CalendarEventInput) -> CalendarEvent: ...

    def delete_event(self, connection_id: uuid.UUID, external_event_id: str) -> None: ...

    def list_events(self, connection_id: uuid.UUID, *, start_from: datetime, start_to: datetime) -> list[CalendarEvent]: ...

    def refresh_token(self, connection_id: uuid.UUID) -> None: ...
