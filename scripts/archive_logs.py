"""Archive old signal log rows to XLSX and prune from the live table.

Run inside the container:
    docker compose exec web python scripts/archive_logs.py
    docker compose exec web python scripts/archive_logs.py --months 6
    docker compose exec web python scripts/archive_logs.py --dry-run

The script uses the retain_months from the database setting (Admin > App Config >
System) unless overridden with --months. Signal logs for closed serials older than
the retention period are exported to SERIAL_ARCHIVE_DIR and deleted from
signal_logs. The serial record is kept so history remains intact. Testing-scope
logs are deleted without archiving.
"""

import argparse
import sys
from pathlib import Path

# Allow running from repo root or scripts/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.settings import get_signal_log_retain_months, DEFAULT_SIGNAL_LOG_RETAIN_MONTHS
from app.signal_log_archive import archive_old_signal_logs


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive old signal log rows.")
    parser.add_argument(
        "--months",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Override retention period in months "
            f"(default: read from DB setting, fallback {DEFAULT_SIGNAL_LOG_RETAIN_MONTHS})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be archived without making any changes.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        retain = args.months if args.months is not None else get_signal_log_retain_months(db)
        print(
            f"Signal log archive — retain_months={retain}"
            f"{' (DRY RUN)' if args.dry_run else ''}"
        )
        result = archive_old_signal_logs(db, retain_months=retain, actor_id=None, dry_run=args.dry_run)

    print(result.summary())
    if result.paths:
        print("Files written:")
        for p in result.paths:
            print(f"  {p}")
    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
