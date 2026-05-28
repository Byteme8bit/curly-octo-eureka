"""Pytest config — adds project root to sys.path so `bot.*` and `watchdog.*` import cleanly."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
