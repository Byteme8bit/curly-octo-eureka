"""Watchdog entry point — optional standalone mode (normally runs inside main.py)."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from watchdog.config import load_settings
from watchdog.engine import WatchdogEngine

PACIFIC = ZoneInfo("America/Los_Angeles")


class PacificFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, PACIFIC)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(PacificFormatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main() -> None:
    setup_logging()
    print(
        "Note: Watchdog is normally started automatically with `python main.py`.\n"
        "Standalone mode does not control the trade bot lifecycle.\n"
    )
    settings = load_settings()
    engine = WatchdogEngine(settings)
    try:
        engine.run_standalone()
    except KeyboardInterrupt:
        print("\n  Watchdog stopped.")
        engine.end_session()
        sys.exit(0)


if __name__ == "__main__":
    main()
