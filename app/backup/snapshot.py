"""
A full, consistent snapshot of every table in the app's schema, written as one
gzip-compressed JSON file. Plain JSON on purpose: readable by any tool, no
pg_dump install needed, and small (the whole database is a few MB).

What a snapshot does NOT make readable: NSS, número de crédito and INE images
are stored encrypted (app/core/crypto.py) and stay encrypted inside the file.
Restoring them only works with the same RENOVA_ENCRYPTION_KEY — keep a copy of
that key somewhere safe and separate from the backups (e.g. a password manager).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import uuid
import warnings
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, select, text
from sqlalchemy.exc import SAWarning
from sqlalchemy.engine import Engine

FORMAT_VERSION = 1
FILE_PREFIX = "stateai-backup-"
FILE_SUFFIX = ".json.gz"


def to_jsonable(value: Any) -> Any:
    """One stable text form per type, so a backup row can be compared with a live row value for value."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value == value.to_integral() else str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return str(value)


def _model_table_for(reflected):
    """
    The app's own model Table when it describes exactly the same columns —
    its types (UUID, Numeric, JSON…) decode values the same way the app and
    the restore read them, so a backup compares equal to an untouched live row.
    Anything the models don't know (or a schema drift) is read as reflected.
    """
    import app.models  # noqa: F401 — populates Base.metadata
    from app.models.base import Base

    model = Base.metadata.tables.get(reflected.name)
    if model is not None and set(model.columns.keys()) == set(reflected.columns.keys()):
        return model
    return reflected


def take_snapshot(engine: Engine, *, schema: str | None = None) -> dict:
    """
    Every row of every table, read inside ONE repeatable-read, read-only
    transaction on Postgres — a single consistent point in time, and nothing
    in the database can be modified by taking it.
    """
    with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            schema = schema or "public"
        metadata = MetaData()
        with warnings.catch_warnings():
            # Expression-based indexes can't be reflected; a data snapshot doesn't need indexes at all.
            warnings.filterwarnings("ignore", message="Skipped unsupported reflection", category=SAWarning)
            metadata.reflect(bind=conn, schema=schema)
        tables: dict[str, dict] = {}
        for reflected in metadata.sorted_tables:
            table = _model_table_for(reflected)
            columns = [column.name for column in table.columns]
            order = list(table.primary_key.columns) or list(table.columns)[:1]
            rows = conn.execute(select(table).order_by(*order)).mappings().all()
            tables[table.name] = {
                "columns": columns,
                "rows": [{name: to_jsonable(row[name]) for name in columns} for row in rows],
            }
        revision = None
        if "alembic_version" in tables and tables["alembic_version"]["rows"]:
            revision = tables["alembic_version"]["rows"][0].get("version_num")
        conn.rollback()
    return {
        "format": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "alembic_revision": revision,
        "row_counts": {name: len(data["rows"]) for name, data in tables.items()},
        "tables": tables,
    }


def write_snapshot(snapshot: dict, directory: Path, *, label: str | None = None) -> Path:
    """
    Writes `stateai-backup-<UTC timestamp>[-label].json.gz` (+ a .sha256 next
    to it) atomically: a crash mid-write never leaves a half file under the
    real name. The label marks manual snapshots, e.g. "antes-de-migracion".
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(snapshot["created_at"]).strftime("%Y%m%d-%H%M%S")
    suffix = "-" + "".join(c if (c.isascii() and c.isalnum()) or c == "-" else "-" for c in label.lower()) if label else ""
    target = directory / f"{FILE_PREFIX}{stamp}{suffix}{FILE_SUFFIX}"
    partial = target.with_name(target.name + ".partial")
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(partial, "wb") as handle:
        handle.write(payload)
    os.replace(partial, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return target


def list_backups(directory: Path) -> list[Path]:
    """Oldest first (the timestamp in the name sorts chronologically)."""
    if not directory.exists():
        return []
    return sorted(directory.glob(f"{FILE_PREFIX}*{FILE_SUFFIX}"))


def prune_backups(directory: Path, keep: int) -> list[Path]:
    """Deletes all but the newest `keep` backups (and their checksums); returns what was removed."""
    removed = []
    backups = list_backups(directory)
    for old in backups[: max(len(backups) - keep, 0)]:
        old.unlink()
        checksum = old.with_name(old.name + ".sha256")
        if checksum.exists():
            checksum.unlink()
        removed.append(old)
    return removed


def load_snapshot(path: Path) -> dict:
    checksum = path.with_name(path.name + ".sha256")
    if checksum.exists():
        expected = checksum.read_text(encoding="utf-8").split()[0]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"{path.name} does not match its .sha256 — the file is damaged or was modified.")
    with gzip.open(path, "rb") as handle:
        snapshot = json.loads(handle.read().decode("utf-8"))
    if snapshot.get("format") != FORMAT_VERSION:
        raise ValueError(f"Unsupported backup format: {snapshot.get('format')!r}")
    return snapshot
