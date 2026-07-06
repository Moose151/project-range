#!/usr/bin/env python3
"""Back up the Docker-hosted SQLite database.

Run from the repository root while Docker Compose can see the running service:

    python scripts/backup_db.py

Use Windows Task Scheduler or cron to run it regularly. The script uses
`docker compose cp`, so it works with the named volume without needing to know
where Docker stores volumes on the host.
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up SEW Range SQLite DB from Docker Compose.")
    parser.add_argument("--service", default="web", help="Docker Compose service name. Default: web")
    parser.add_argument("--db-path", default="/app/data/range.db", help="Path to DB inside the container.")
    parser.add_argument("--output-dir", default="backups", help="Directory for backup files.")
    parser.add_argument("--keep", type=int, default=30, help="Keep this many newest backups; 0 disables pruning.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        out_dir.chmod(0o700)
    except OSError as exc:
        print(f"WARNING: could not set owner-only permissions on {out_dir}: {exc}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    dest = out_dir / f"range-{stamp}.db"
    source = f"{args.service}:{args.db_path}"

    subprocess.run(["docker", "compose", "cp", source, str(dest)], check=True)
    try:
        dest.chmod(0o600)
    except OSError as exc:
        print(f"WARNING: could not set owner-only permissions on {dest}: {exc}")
    print(f"Backed up {source} -> {dest}")

    if args.keep > 0:
        backups = sorted(out_dir.glob("range-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[args.keep:]:
            old.unlink()
            print(f"Pruned old backup {old}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
