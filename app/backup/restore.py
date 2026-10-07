"""
Selective restore of ONE advisor's Renova work (their cases + follow-up
history) — or specific cases — from a snapshot, without touching anyone
else's data. Two steps, always:

  1. plan_renova_restore(...)  — read-only: what's missing now, what differs,
     what's identical. Nothing is written.
  2. apply_renova_restore(...) — one transaction: re-inserts the MISSING rows
     (a deleted case and its follow-ups come back with the same ids), and only
     with overwrite=True also puts back the backup version of rows that were
     changed since. Every restored case gets an audit-log entry.

Without overwrite a restore can never undo newer, legitimate edits — it only
fills holes. That's the safe default when "something got deleted".
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, Table, Uuid, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.backup.snapshot import to_jsonable
from app.models.organization import User
from app.models.renova_case import RenovaCase
from app.models.renova_follow_up import RenovaFollowUpActivity
from app.services.audit_service import AuditService

# Restore order matters: a follow-up points at its case.
_CASES: Table = RenovaCase.__table__  # type: ignore[assignment]
_FOLLOW_UPS: Table = RenovaFollowUpActivity.__table__  # type: ignore[assignment]


@dataclass
class RowChange:
    table: str
    id: str
    status: str  # "missing" | "changed" | "same"
    label: str
    backup_row: dict
    changed_fields: list[str] = field(default_factory=list)


@dataclass
class RestorePlan:
    backup_created_at: str
    advisor_email: str | None
    advisor_id: str | None
    rows: list[RowChange]

    def count(self, table: str, status: str) -> int:
        return sum(1 for row in self.rows if row.table == table and row.status == status)


def _from_jsonable(table: Table, name: str, value: Any) -> Any:
    """The inverse of to_jsonable for one column, using the model's own column type."""
    if value is None:
        return None
    if isinstance(value, dict) and "__b64__" in value:
        return base64.b64decode(value["__b64__"])
    column_type = table.columns[name].type
    if isinstance(column_type, Uuid):
        return uuid.UUID(value)
    if isinstance(column_type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column_type, Date):
        return date.fromisoformat(value)
    if isinstance(column_type, Numeric):
        return Decimal(value)
    return value


def _backup_rows(snapshot: dict, table: Table) -> list[dict]:
    data = snapshot["tables"].get(table.name)
    if data is None:
        raise ValueError(f"The backup has no '{table.name}' table.")
    return data["rows"]


def _current_rows(session: Session, table: Table, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = session.execute(select(table).where(table.c.id.in_([uuid.UUID(i) for i in ids]))).mappings().all()
    return {str(row["id"]): {name: to_jsonable(row[name]) for name in table.columns.keys()} for row in rows}


def _compare(table: Table, backup_rows: list[dict], current: dict[str, dict], label_of) -> list[RowChange]:
    changes = []
    for row in backup_rows:
        live = current.get(row["id"])
        if live is None:
            changes.append(RowChange(table.name, row["id"], "missing", label_of(row), row))
            continue
        # updated_at always moves on any edit; it's not a "difference" worth showing on its own.
        diff = [name for name in table.columns.keys() if name != "updated_at" and row.get(name) != live.get(name)]
        changes.append(RowChange(table.name, row["id"], "changed" if diff else "same", label_of(row), row, diff))
    return changes


def plan_renova_restore(
    snapshot: dict,
    engine: Engine,
    *,
    advisor_email: str | None = None,
    case_ids: list[str] | None = None,
) -> RestorePlan:
    """Read-only. Picks the advisor's cases the same way the app decides what they see: assigned to them OR created by them."""
    if not advisor_email and not case_ids:
        raise ValueError("Give an advisor email or at least one case id.")

    advisor_id = None
    if advisor_email:
        wanted = advisor_email.strip().lower()
        users = _backup_rows(snapshot, User.__table__)  # type: ignore[arg-type]
        match = next((u for u in users if (u.get("email") or "").lower() == wanted), None)
        if match is None:
            raise ValueError(f"No user with email {advisor_email} in this backup.")
        advisor_id = match["id"]

    wanted_ids = set(case_ids or [])
    cases = [
        row
        for row in _backup_rows(snapshot, _CASES)
        if row["id"] in wanted_ids
        or (advisor_id is not None and advisor_id in (row.get("assigned_user_id"), row.get("created_by_user_id")))
    ]
    case_names = {row["id"]: row.get("owner_name") or row["id"] for row in cases}
    follow_ups = [row for row in _backup_rows(snapshot, _FOLLOW_UPS) if row["renova_case_id"] in case_names]

    with Session(engine) as session:
        rows = _compare(_CASES, cases, _current_rows(session, _CASES, list(case_names)), lambda r: r.get("owner_name") or r["id"])
        rows += _compare(
            _FOLLOW_UPS,
            follow_ups,
            _current_rows(session, _FOLLOW_UPS, [r["id"] for r in follow_ups]),
            lambda r: f"{case_names[r['renova_case_id']]} · {r.get('activity_type')} {r.get('occurred_at', '')[:10]}",
        )
    return RestorePlan(snapshot["created_at"], advisor_email, advisor_id, rows)


def apply_renova_restore(plan: RestorePlan, engine: Engine, *, overwrite: bool = False) -> dict[str, int]:
    """One transaction: all of it lands, or none of it does."""
    counts = {"inserted": 0, "overwritten": 0}
    with Session(engine) as session, session.begin():
        audit = AuditService(session)
        restored_cases: dict[str, RowChange] = {}
        for table in (_CASES, _FOLLOW_UPS):  # cases before the follow-ups that reference them
            for change in (row for row in plan.rows if row.table == table.name):
                values = {name: _from_jsonable(table, name, change.backup_row.get(name)) for name in table.columns.keys()}
                if change.status == "missing":
                    session.execute(insert(table).values(**values))
                    counts["inserted"] += 1
                elif change.status == "changed" and overwrite:
                    session.execute(update(table).where(table.c.id == values["id"]).values(**values))
                    counts["overwritten"] += 1
                else:
                    continue
                case_id = change.id if table is _CASES else change.backup_row["renova_case_id"]
                restored_cases.setdefault(case_id, change)
        for case_id in restored_cases:
            case_row = next((r.backup_row for r in plan.rows if r.table == _CASES.name and r.id == case_id), None)
            if case_row is None:
                continue
            audit.record(
                organization_id=uuid.UUID(case_row["organization_id"]),
                actor_user_id=None,
                entity_type="renova_case",
                entity_id=uuid.UUID(case_id),
                action="RENOVA_CASE_RESTORED_FROM_BACKUP",
                after={"backup_created_at": plan.backup_created_at, "overwrite": overwrite},
            )
    return counts
