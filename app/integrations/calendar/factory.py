"""
Mirrors app/ai/llm/factory.py's shape for the same reason: one small
if/elif that a real second/third provider would justify replacing with a
registry, not needed yet at three stubs. Not called from anywhere in this
codebase today — see the README's Calendar Integration Architecture section.
"""

from __future__ import annotations

from app.integrations.calendar.apple import AppleCalendarProvider
from app.integrations.calendar.base import CalendarProvider
from app.integrations.calendar.google import GoogleCalendarProvider
from app.integrations.calendar.notion import NotionCalendarProvider


def build_calendar_provider(provider_name: str) -> CalendarProvider:
    if provider_name == "google":
        return GoogleCalendarProvider()
    if provider_name == "apple":
        return AppleCalendarProvider()
    if provider_name == "notion":
        return NotionCalendarProvider()
    raise ValueError(f"Unknown calendar provider: {provider_name!r}")
