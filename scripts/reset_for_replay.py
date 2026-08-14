#!/usr/bin/env python3
"""Full reset checklist before historical paper replay."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BALANCES = {
    "ETH": 0.49501,
    "USD": 415.90,
    "ADA": 24.620422,
    "KFEE": 881.92,
}
BASELINE_USD = 1349.04


def set_env(text: str, key: str, value: str) -> str:
    if re.search(rf"^{re.escape(key)}=", text, flags=re.M):
        return re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
    return text.rstrip() + f"\n{key}={value}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset all state for historical replay")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--no-stop-services", action="store_true")
    args = parser.parse_args()
    root: Path = args.root
    env_path = root / ".env"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = root / "archive" / f"replay-reset-{stamp}"
    archive.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    if not args.no_stop_services:
        for unit in ("tradebot.service", "tradebot-activity-watch.timer"):
            # Prefer sudo so cursor can stop units when allowed
            subprocess.run(["sudo", "systemctl", "stop", unit], check=False, timeout=60)

    paths = [
        root / ".paper_state.json",
        root / "paper_portfolio.json",
        root / "paper_baseline.json",
        root / ".watchdog_state.json",
        root / ".tradebot_goals_state.json",
        root / "logs" / "discord_chat.log",
        root / "logs" / "trade_diagnosis.json",
        env_path,
    ]
    for p in paths:
        if p.exists():
            shutil.copy2(p, archive / p.name)

    # Paper state
    state = {
        "balances": dict(BALANCES),
        "cost_basis": {},
        "trades": [],
        "risk": {
            "peak_portfolio": BASELINE_USD,
            "baseline_portfolio": BASELINE_USD,
            "paused_until": None,
            "hibernate_alert_sent": False,
            "last_trade_at": None,
            "session_started_at": now,
            "trades_this_hour": 0,
            "hour_window_start": now,
            "reevaluation_mode": False,
            "circuit_breaker_at": None,
            "adaptive_alert_sent": False,
            "adaptive_relax_attempts": 0,
            "adaptive_suspended": False,
            "adaptive_suspended_at": None,
            "total_trades": 0,
            "live_trades_completed": 0,
            "strategy_stats": {},
        },
    }
    (root / ".paper_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    (root / "paper_portfolio.json").write_text(
        json.dumps(
            {
                "portfolio_usd": BASELINE_USD,
                "baseline_pnl": 0.0,
                "updated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
                "source": "historical_replay_reset",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "paper_baseline.json").write_text(
        json.dumps(
            {
                "source": "kraken_screenshot_manual_replay",
                "balances": dict(BALANCES),
                "portfolio_usd": BASELINE_USD,
                "captured_at": now,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Watchdog — clear scoring, keep offsets
    wd_path = root / ".watchdog_state.json"
    wd = json.loads(wd_path.read_text(encoding="utf-8")) if wd_path.exists() else {}
    keep_offsets = wd.get("file_offsets") or {}
    keep_receipts = wd.get("seen_receipts") or []
    wd = {
        "file_offsets": keep_offsets,
        "seen_receipts": keep_receipts,
        "last_pnl_band": 0,
        "last_live_pnl_band": 0,
        "last_drawdown_warn": 0.0,
        "seen_error_keys": {},
        "stale_alert_sent": False,
        "reevaluation_alerted": False,
        "error_timestamps": [],
        "watchdog_error_timestamps": [],
        "trades_session": 0,
        "watchdog_pause_count": 0,
        "last_watchdog_pause_at": None,
        "last_heartbeat_at": 0.0,
        "last_milestone_alert_at": 0.0,
        "recent_errors": [],
        "error_pin_windows": {},
        "seen_diagnostics": [],
        "session_started_at": now,
        "last_portfolio": BASELINE_USD,
        "last_baseline": BASELINE_USD,
    }
    wd_path.write_text(json.dumps(wd, indent=2) + "\n", encoding="utf-8")

    goals = {
        "achieved_tiers": [0],
        "last_announced_tier": 0,
        "crash_hold_active": False,
        "crash_hold_since": None,
        "crash_hold_reason": "",
        "crash_hold_triggers": [],
        "session_start_portfolio": BASELINE_USD,
        "session_start_at": now,
        "last_portfolio_usd": BASELINE_USD,
        "last_tier": 0,
    }
    (root / ".tradebot_goals_state.json").write_text(
        json.dumps(goals, indent=2) + "\n", encoding="utf-8"
    )

    chat = root / "logs" / "discord_chat.log"
    chat.parent.mkdir(parents=True, exist_ok=True)
    chat.write_text("", encoding="utf-8")
    diag = root / "logs" / "trade_diagnosis.json"
    if diag.exists():
        diag.unlink()

    # Env for realistic replay
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    updates = {
        "DISCORD_QUIET_MODE": "1",
        "WATCHDOG_QUIET_MODE": "1",
        "AUDITOR_DISCORD_QUIET": "1",
        "DISCORD_ENABLED": "1",
        "FEE_FORCE_STATIC": "0",
        "FEE_RATE": "0.0016",
        "MAKER_FEE_RATE": "0.0016",
        "PAPER_USE_MAKER_FEES": "1",
        "MIN_TRADE_EDGE": "0.0018",
        "CRYPTO_MIN_TRADE_EDGE": "0.0018",
        "MIN_NET_PROFIT_PCT": "0.0001",
        "SLIPPAGE_BUFFER_PCT": "0.0001",
        "MIN_ETH_RESERVE": "0.40",
        "LIVE_MIN_ETH_RESERVE": "0.40",
        "WHALE_WATCH_ENABLED": "0",
        "WHALE_FOLLOW_ENABLED": "0",
        "CRASH_HOLD_ENABLED": "0",
        "PAPER_ANCHOR_TO_LIVE": "0",
        "LIVE_ENABLED": "0",
        "LIVE_MIRROR_PAPER": "0",
        "GOAL_EVOLUTION_ENABLED": "1",
        "GOAL_TIER0_STRATEGIES": "cross_momentum,stat_arb,triangular_arbitrage",
        "GOAL_TIER1_STRATEGIES": "cross_momentum,stat_arb,triangular_arbitrage",
        "GOAL_TIER2_STRATEGIES": "cross_momentum,stat_arb,triangular_arbitrage",
        "GOAL_TIER3_STRATEGIES": "cross_momentum,stat_arb,triangular_arbitrage",
        "STRATEGIES": "cross_momentum,stat_arb,triangular_arbitrage",
        "CANDLE_TIMEFRAME": "15m",
        "CANDLE_LIMIT": "60",
        "MOMENTUM_TIMEFRAMES": "15m,1h",
        "INITIAL_BALANCES": json.dumps(BALANCES, separators=(",", ":")),
        "PROFIT_ONLY_MODE": "1",
    }
    for k, v in updates.items():
        text = set_env(text, k, v)
    env_path.write_text(text, encoding="utf-8")

    print(f"archive={archive}")
    print(f"balances={BALANCES}")
    print("reset_ok=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
