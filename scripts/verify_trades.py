#!/usr/bin/env python3
"""Thin wrapper: python scripts/verify_trades.py [--last N] [--since DATE] [--json] [--html]"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.verifier.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
