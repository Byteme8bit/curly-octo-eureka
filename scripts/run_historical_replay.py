#!/usr/bin/env python3
"""Run 7-day historical paper replay with realistic maker fees."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical OHLCV paper replay")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--timeframe", default="15m", help="OHLCV timeframe (15m covers 7d within Kraken public OHLC limit)")
    parser.add_argument("--duration-minutes", type=float, default=90.0)
    parser.add_argument("--asap", action="store_true", help="No wall-clock pacing")
    parser.add_argument("--no-refresh-cache", action="store_true")
    parser.add_argument("--skip-reset", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    asap = args.asap or os.getenv("REPLAY_ASAP", "0") == "1"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.skip_reset:
        from scripts.reset_for_replay import main as reset_main

        # reset_for_replay uses argparse from sys.argv — call via subprocess-like
        import subprocess

        rc = subprocess.call(
            [sys.executable, str(args.root / "scripts" / "reset_for_replay.py"), "--root", str(args.root)],
        )
        if rc != 0:
            return rc

    # Load settings after reset mutated .env
    from dotenv import load_dotenv

    load_dotenv(args.root / ".env", override=True)

    from bot.engine import TradingEngine
    from bot.strategies.registry import build_orchestrator
    from bot.replay.runner import run_replay
    from config import load_settings

    settings = load_settings()

    def build_bot():
        strategy = build_orchestrator(settings)
        return TradingEngine(settings, strategy)

    summary = run_replay(
        settings=settings,
        build_bot=build_bot,
        cache_dir=args.root / "logs" / "replay",
        days=args.days,
        timeframe=args.timeframe,
        duration_minutes=args.duration_minutes,
        asap=asap,
        refresh_cache=not args.no_refresh_cache,
    )
    print(json_dumps(summary))
    return 0


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
