"""
Who may see which Renova cases — the single definition every Renova read and
write path builds on (table, counts, Kanban board, case detail, follow-up,
protected data, INE images and the Renova chat), so no path can drift.

  * owner / admin / agent: every case in their organization (unchanged
    behavior — organization_id is still the tenant boundary).
  * renova_agent: only the cases they created OR that are assigned to them,
    inside their organization. Anything else answers 404 exactly like a case
    of another organization, so ids can't be probed.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import ColumnElement, or_

from app.core.security import get_current_org_user
from app.models.renova_case import RenovaCase
from app.schemas.user import CurrentUser

RENOVA_ONLY_ROLES: tuple[str, ...] = ("renova_agent",)


def renova_owner_filter(current_user: CurrentUser) -> uuid.UUID | None:
    """The user id a caller's Renova view is restricted to, or None when they see the whole organization."""
    return current_user.id if current_user.role in RENOVA_ONLY_ROLES else None


def visible_cases_clause(organization_id: uuid.UUID, visible_to: uuid.UUID | None) -> tuple[ColumnElement[bool], ...]:
    """WHERE clauses for the cases a caller may see — organization first, then (for a Renova-only advisor) ownership."""
    clauses: tuple[ColumnElement[bool], ...] = (RenovaCase.organization_id == organization_id,)
    if visible_to is not None:
        clauses += (or_(RenovaCase.assigned_user_id == visible_to, RenovaCase.created_by_user_id == visible_to),)
    return clauses


def renova_case_scope(current_user: CurrentUser) -> tuple[ColumnElement[bool], ...]:
    return visible_cases_clause(current_user.organization_id, renova_owner_filter(current_user))


def require_crm_access(current_user: CurrentUser = Depends(get_current_org_user)) -> CurrentUser:
    """
    Mounted on every non-Renova router (see app/api/router.py): a Renova-only
    advisor works inside the Renova module and never reads the organization's
    Contacts, Properties, Pipeline, Tasks, Appointments, AI agents, etc.
    """
    if current_user.role in RENOVA_ONLY_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account only has access to the Renova module.")
    return current_user
