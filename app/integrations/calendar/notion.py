"""Notion (calendar-style database) — stub only. See app/integrations/calendar/base.py; no real Notion API call happens anywhere in this class."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.integrations.calendar.base import CalendarEvent, CalendarEventInput, CalendarIntegrationNotImplementedError


class NotionCalendarProvider:
    def create_event(self, connection_id: uuid.UUID, event: CalendarEventInput) -> CalendarEvent:
        raise CalendarIntegrationNotImplementedError("Notion")

    def update_event(self, connection_id: uuid.UUID, external_event_id: str, event: CalendarEventInput) -> CalendarEvent:
        raise CalendarIntegrationNotImplementedError("Notion")

    def delete_event(self, connection_id: uuid.UUID, external_event_id: str) -> None:
        raise CalendarIntegrationNotImplementedError("Notion")

    def list_events(self, connection_id: uuid.UUID, *, start_from: datetime, start_to: datetime) -> list[CalendarEvent]:
        raise CalendarIntegrationNotImplementedError("Notion")

    def refresh_token(self, connection_id: uuid.UUID) -> None:
        raise CalendarIntegrationNotImplementedError("Notion")
