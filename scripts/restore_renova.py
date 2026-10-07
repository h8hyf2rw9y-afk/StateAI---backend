"""
Put back an advisor's Renova cases (and their follow-up history), or specific
cases, from a backup, without touching anyone else's data.

Always look first (nothing is written without --apply):
    uv run python scripts/restore_renova.py --advisor ana@gmail.com
    uv run python scripts/restore_renova.py --case 6b4c60fe-b904-4823-8854-ab5b8a2eee6e
    uv run python scripts/restore_renova.py --advisor ana@gmail.com --backup <file.json.gz>

Then apply:
    ... --apply               re-creates only what is MISSING (never undoes newer edits)
    ... --apply --overwrite   also puts back the backup version of rows changed since

--apply first takes a fresh "antes-de-restaurar" backup, so a restore itself can be undone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402

from app.backup.restore import apply_renova_restore, plan_renova_restore  # noqa: E402
from app.backup.snapshot import list_backups, load_snapshot, take_snapshot, write_snapshot  # noqa: E402
from app.core.config import settings  # noqa: E402
from scripts.backup_db import DEFAULT_DIR  # noqa: E402

STATUS_LABELS = {"missing": "FALTA (se volverá a crear)", "changed": "CAMBIÓ desde el respaldo", "same": "igual"}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--advisor", help="Email of the advisor whose Renova work to restore.")
    parser.add_argument("--case", action="append", default=[], help="A case id to restore (repeatable).")
    parser.add_argument("--backup", type=Path, help="Backup file (default: the newest in the backup folder).")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--apply", action="store_true", help="Actually write. Without it this only shows the plan.")
    parser.add_argument("--overwrite", action="store_true", help="With --apply: also replace rows changed since the backup.")
    args = parser.parse_args()

    if not args.advisor and not args.case:
        parser.error("Indica --advisor EMAIL o --case ID.")
    backups = list_backups(args.dir)
    backup = args.backup or (backups[-1] if backups else None)
    if backup is None:
        parser.error(f"No hay respaldos en {args.dir}")

    snapshot = load_snapshot(backup)
    engine = create_engine(settings.database_url)
    plan = plan_renova_restore(snapshot, engine, advisor_email=args.advisor, case_ids=args.case)

    print(f"Respaldo: {backup.name} (tomado {snapshot['created_at']})")
    for table, title in (("renova_cases", "Expedientes"), ("renova_follow_up_activities", "Seguimientos")):
        rows = [r for r in plan.rows if r.table == table]
        print(
            f"\n{title}: {len(rows)} en el respaldo · faltan {plan.count(table, 'missing')}"
            f" · cambiaron {plan.count(table, 'changed')}"
        )
        for row in rows:
            if row.status == "same":
                continue
            extra = f" — campos: {', '.join(row.changed_fields)}" if row.changed_fields else ""
            print(f"  [{STATUS_LABELS[row.status]}] {row.label}{extra}")

    to_insert = sum(1 for r in plan.rows if r.status == "missing")
    to_overwrite = sum(1 for r in plan.rows if r.status == "changed") if args.overwrite else 0
    if not args.apply:
        extra = f" y se reemplazarían {to_overwrite}" if args.overwrite else ""
        print(f"\nVista previa: se crearían {to_insert} filas{extra}. Agrega --apply para aplicarlo.")
        return 0
    if to_insert == 0 and to_overwrite == 0:
        print("\nNada que restaurar.")
        return 0

    safety = write_snapshot(take_snapshot(engine), args.dir, label="antes-de-restaurar")
    print(f"\nRespaldo de seguridad previo: {safety.name}")
    result = apply_renova_restore(plan, engine, overwrite=args.overwrite)
    print(f"Restaurado: {result['inserted']} filas creadas, {result['overwritten']} reemplazadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
