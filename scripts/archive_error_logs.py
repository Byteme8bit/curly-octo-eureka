"""Archive handled fatal-error logs into `Error Logs/archived/`.

Usage:
    # archive every loose log
    python scripts/archive_error_logs.py --all --reason "handled in feature 011"

    # archive a single file
    python scripts/archive_error_logs.py "Error Logs/2026-05-25_131331_fatal.txt"

    # list logs without moving anything
    python scripts/archive_error_logs.py --list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.fatal_error_log import (  # noqa: E402
    ARCHIVE_DIR,
    ERROR_DIR,
    archive_all_logs,
    archive_log,
)


def _list() -> int:
    if not ERROR_DIR.exists():
        print(f"No Error Logs folder at {ERROR_DIR}")
        return 0
    loose = sorted(p for p in ERROR_DIR.iterdir() if p.is_file() and p.suffix == ".txt")
    archived = sorted(ARCHIVE_DIR.glob("*.txt")) if ARCHIVE_DIR.exists() else []

    print(f"Error Logs: {ERROR_DIR}")
    print(f"  loose:    {len(loose)} file(s)")
    for p in loose:
        print(f"    - {p.name}")
    print(f"  archived: {len(archived)} file(s)")
    for p in archived[-10:]:
        print(f"    - {p.name}")
    if len(archived) > 10:
        print(f"    ... ({len(archived) - 10} more)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="Specific log file to archive")
    parser.add_argument("--all", action="store_true", help="Archive every loose log")
    parser.add_argument("--list", action="store_true", help="List logs without archiving")
    parser.add_argument(
        "--reason", default="handled", help="Reason appended to archived file footer"
    )
    args = parser.parse_args(argv)

    if args.list:
        return _list()

    if args.all:
        moved = archive_all_logs(reason=args.reason)
        if not moved:
            print("No loose logs to archive.")
            return 0
        print(f"Archived {len(moved)} log(s) -> {ARCHIVE_DIR}")
        for p in moved:
            print(f"  - {p.name}")
        return 0

    if not args.path:
        parser.error("provide a path, --all, or --list")

    src = Path(args.path)
    if not src.exists():
        print(f"Not found: {src}", file=sys.stderr)
        return 1
    dest = archive_log(src, reason=args.reason)
    if dest == src:
        print(f"Could not archive {src}", file=sys.stderr)
        return 1
    print(f"Archived: {src.name} -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
