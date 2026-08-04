"""Apply Kraken Day-Trade Robot revival profile to .env safely.

Usage:
  python scripts/apply_revival_profile.py phase1   # conservative paper-only
  python scripts/apply_revival_profile.py phase2   # day-trader paper mode
  python scripts/apply_revival_profile.py live     # live single-hop (requires validation pass)

Preserves existing KRAKEN_API_KEY / KRAKEN_API_SECRET and Discord settings when present.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"

PRESERVE_KEYS = frozenset(
    {
        "KRAKEN_API_KEY",
        "KRAKEN_API_SECRET",
        "KRAKEN_FUTURES_API_KEY",
        "KRAKEN_FUTURES_API_SECRET",
        "DISCORD_ENABLED",
        "DISCORD_WEBHOOK",
        "DISCORD_BOT_TOKEN",
        "DISCORD_CHANNEL_ID",
        "DISCORD_ALLOWED_USER_IDS",
        "GEMINI_API_KEY",
    }
)

PHASE1_OVERRIDES: dict[str, str] = {
    "LIVE_ENABLED": "0",
    "LIVE_MIRROR_PAPER": "0",
    "LIVE_ALLOW_TRIANGULAR": "0",
    "LIVE_MAX_ROUTE_LEGS": "1",
    "LIVE_DRAWDOWN_HALT_PCT": "0.10",
    "LIVE_STRICT_PROFIT": "1",
    "LIVE_MIN_ETH_RESERVE": "0.5",
    "STRATEGIES": "cross_momentum",
    "PROFIT_ONLY_MODE": "1",
    "ENABLE_EQUITIES": "0",
    "DCA_ENABLED": "0",
    "AUDITOR_ENABLED": "0",
    "ENABLE_FUTURES": "0",
    "LIVE_FUTURES_ENABLED": "0",
    "DAY_TRADER_MODE": "0",
    "CRYPTO_DAY_TRADE_MODE": "0",
    "RESET_PAPER_STATE": "0",
}

PHASE2_OVERRIDES: dict[str, str] = {
    **PHASE1_OVERRIDES,
    "DAY_TRADER_MODE": "1",
    "CRYPTO_DAY_TRADE_MODE": "1",
}

LIVE_OVERRIDES: dict[str, str] = {
    **PHASE2_OVERRIDES,
    "LIVE_ENABLED": "1",
    "LIVE_TRADING_CONFIRM": "I_ACCEPT_REAL_MONEY",
    "LIVE_ALLOWED_ASSETS": "ETH,ADA",
    "LIVE_MAX_TRADE_USD": "25",
    "LIVE_MAX_USD_PER_TRADE": "25",
    "LIVE_MAX_TRADES": "5",
    "LIVE_MIRROR_MIN_CONFIDENCE": "confirm",
    "LIVE_MIRROR_UNCERTAIN": "0",
}


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def _apply_overrides(content: str, overrides: dict[str, str]) -> str:
    lines = content.splitlines()
    seen: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in overrides:
                new_lines.append(f"{key}={overrides[key]}")
                seen.add(key)
                continue
        new_lines.append(line)

    for key, value in overrides.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    return "\n".join(new_lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("phase1", "phase2", "live"),
        help="Revival profile phase to apply",
    )
    args = parser.parse_args(argv)

    if not EXAMPLE_PATH.exists():
        print(f"FAIL: missing {EXAMPLE_PATH}")
        return 1

    overrides = {
        "phase1": PHASE1_OVERRIDES,
        "phase2": PHASE2_OVERRIDES,
        "live": LIVE_OVERRIDES,
    }[args.phase]

    preserved: dict[str, str] = {}
    if ENV_PATH.exists() and ENV_PATH.stat().st_size > 0:
        preserved = {
            k: v
            for k, v in _parse_env(ENV_PATH.read_text(encoding="utf-8")).items()
            if k in PRESERVE_KEYS and v
        }
        backup = ROOT / "archive" / f".env.backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ENV_PATH, backup)
        print(f"Backed up existing .env to {backup}")

    base = EXAMPLE_PATH.read_text(encoding="utf-8")
    merged = {**overrides, **preserved}
    ENV_PATH.write_text(_apply_overrides(base, merged), encoding="utf-8")
    print(f"Applied {args.phase} profile to {ENV_PATH}")

    if not merged.get("KRAKEN_API_KEY") or not merged.get("KRAKEN_API_SECRET"):
        print("WARN: KRAKEN_API_KEY / KRAKEN_API_SECRET missing — add keys before anchor/start")
        return 2

    if args.phase == "live":
        print("LIVE profile applied — real money armed. Restart TradeBot after review.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
