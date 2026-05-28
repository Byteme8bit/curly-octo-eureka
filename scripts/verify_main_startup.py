r"""Smoke test: main.py should import cleanly and surface fatal errors via the logger.

Run from project root:
    .\.venv\Scripts\python.exe .\scripts\verify_main_startup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    failures: list[str] = []

    try:
        from bot.fatal_error_log import ERROR_DIR, log_fatal
        print(f"OK: bot.fatal_error_log imports; ERROR_DIR = {ERROR_DIR}")
    except Exception as exc:
        failures.append(f"fatal_error_log import: {exc}")

    try:
        try:
            raise RuntimeError("synthetic")
        except RuntimeError as exc:
            path = log_fatal(exc, context="verify_main_startup")
        print(f"OK: log_fatal wrote {path}")
        path.unlink(missing_ok=True)
    except Exception as exc:
        failures.append(f"log_fatal: {exc}")

    try:
        import main  # noqa: F401
        print("OK: main.py imports without executing")
    except Exception as exc:
        failures.append(f"main import: {exc}")

    try:
        from bot.local_time import PACIFIC
        print(f"OK: PACIFIC tz loads ({PACIFIC})")
    except Exception as exc:
        failures.append(f"PACIFIC tz: {exc}")

    if failures:
        print()
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print()
    print("SUCCESS: all startup imports verified")
    return 0



if __name__ == "__main__":
    sys.exit(main())
