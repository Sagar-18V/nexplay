"""
Bring any NexPay database to the latest schema. Used by the `migrate` service in docker
compose (it runs once, before the API and workers start).

Three cases:
  1. Fresh database                    -> alembic upgrade head (builds everything).
  2. Prisma-managed database (pre-Step 7: `_prisma_migrations` exists, no Alembic yet)
                                       -> verify all 4 Prisma migrations are applied,
                                          stamp 0001_prisma_baseline, then upgrade head.
  3. Already on Alembic                -> alembic upgrade head (no-op when current).

Anything else (tables but no migration history) is refused rather than guessed at;
`--adopt-unmanaged` stamps it anyway, for databases you've checked by hand.

    python -m app.ops.migrate [--adopt-unmanaged]
"""
import argparse
import importlib.util
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings, to_sync_dsn

API_ROOT = Path(__file__).resolve().parents[2]
BASELINE = "0001_prisma_baseline"


def _baseline_names() -> list[str]:
    path = API_ROOT / "migrations" / "versions" / "0001_prisma_baseline.py"
    spec = importlib.util.spec_from_file_location("baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PRISMA_MIGRATION_NAMES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt-unmanaged", action="store_true")
    args = ap.parse_args()

    cfg = Config(str(API_ROOT / "alembic.ini"))
    engine = create_engine(to_sync_dsn(get_settings().database_url))
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" in tables:
            state = "alembic"
        elif "_prisma_migrations" in tables:
            applied = {r[0] for r in conn.execute(text(
                "SELECT migration_name FROM _prisma_migrations "
                "WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL"))}
            missing = [n for n in _baseline_names() if n not in applied]
            if missing:
                print(f"REFUSING: Prisma migrations not applied: {missing}. Run `prisma migrate deploy` "
                      "with the last Express release first.", file=sys.stderr)
                return 2
            state = "prisma"
        elif tables - {"alembic_version"}:
            if not args.adopt_unmanaged:
                print(f"REFUSING: {len(tables)} tables but no migration history. Verify the schema matches "
                      f"{BASELINE}, then rerun with --adopt-unmanaged.", file=sys.stderr)
                return 2
            state = "unmanaged"
        else:
            state = "fresh"
    engine.dispose()

    if state in ("prisma", "unmanaged"):
        print(f"[migrate] adopting existing {state} schema: stamping {BASELINE}")
        command.stamp(cfg, BASELINE)
    print(f"[migrate] state={state}: upgrading to head")
    command.upgrade(cfg, "head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
