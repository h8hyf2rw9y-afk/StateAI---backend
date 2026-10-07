"""
Full snapshot of the app's database into a gzip-compressed JSON file.

Usage:
    uv run python scripts/backup_db.py                         # daily backup, keeps the newest 30
    uv run python scripts/backup_db.py --label antes-de-migracion
    uv run python scripts/backup_db.py --list                  # what backups exist

Where: STATEAI_BACKUP_DIR, or by default %USERPROFILE%\\OneDrive\\StateAI-respaldos
(OneDrive keeps a cloud copy, so losing this PC doesn't lose the backups).
Read-only against the database. Run it before any migration or bulk change.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402

from app.backup.snapshot import list_backups, load_snapshot, prune_backups, take_snapshot, write_snapshot  # noqa: E402
from app.core.config import settings  # noqa: E402

DEFAULT_DIR = Path(os.environ.get("STATEAI_BACKUP_DIR") or Path.home() / "OneDrive" / "StateAI-respaldos")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="Backup folder.")
    parser.add_argument("--keep", type=int, default=30, help="How many backups to keep (newest first).")
    parser.add_argument("--label", help='Optional tag for manual snapshots, e.g. "antes-de-migracion".')
    parser.add_argument("--list", action="store_true", help="List existing backups and exit.")
    args = parser.parse_args()

    if args.list:
        backups = list_backups(args.dir)
        if not backups:
            print(f"No hay respaldos en {args.dir}")
        for path in backups:
            counts = load_snapshot(path)["row_counts"]
            print(
                f"{path.name}  ·  {counts.get('renova_cases', 0)} expedientes, "
                f"{counts.get('renova_follow_up_activities', 0)} seguimientos, {counts.get('users', 0)} usuarios"
            )
        return 0

    engine = create_engine(settings.database_url)
    snapshot = take_snapshot(engine)
    path = write_snapshot(snapshot, args.dir, label=args.label)
    load_snapshot(path)  # re-read what was written (checksum + parse) before trusting it
    removed = prune_backups(args.dir, args.keep)
    counts = snapshot["row_counts"]
    print(f"Respaldo guardado: {path}")
    print(f"  {sum(counts.values())} filas en {len(counts)} tablas · migración {snapshot['alembic_revision']}")
    print(
        f"  {counts.get('renova_cases', 0)} expedientes Renova, "
        f"{counts.get('renova_follow_up_activities', 0)} seguimientos, {counts.get('users', 0)} usuarios"
    )
    if removed:
        print(f"  Respaldos antiguos eliminados: {len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
