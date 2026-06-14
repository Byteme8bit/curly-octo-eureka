"""Repair truncated .paper_state.json by dropping the incomplete trailing trade."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".paper_state.json"
PORTFOLIO = ROOT / "paper_portfolio.json"
BACKUP = ROOT / ".paper_state.json.corrupt-bak"


def _default_risk() -> dict:
    risk = {
        "peak_portfolio": 3540.0,
        "baseline_portfolio": 2033.55,
        "paused_until": None,
        "hibernate_alert_sent": False,
        "last_trade_at": None,
        "leader_symbol": "ATOM/USD",
        "leader_since": None,
        "trades_this_hour": 0,
        "hour_window_start": None,
        "reevaluation_mode": False,
        "circuit_breaker_at": None,
        "session_started_at": None,
        "adaptive_alert_sent": False,
        "adaptive_relax_attempts": 0,
        "adaptive_suspended": False,
        "adaptive_suspended_at": None,
        "dominant_strategy": None,
        "dominant_since": None,
        "growth_window_start_at": None,
        "growth_window_start_value": 0.0,
        "strategy_stats": {},
        "total_trades": 0,
        "live_trades_completed": 0,
    }
    if PORTFOLIO.exists():
        try:
            snap = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
            total = float(snap.get("portfolio_usd", 0.0))
            pnl = float(snap.get("baseline_pnl", 0.0))
            dd = float(snap.get("drawdown_pct", 0.0))
            if total > 0:
                risk["peak_portfolio"] = round(total / max(1e-9, 1.0 - dd), 2)
                risk["baseline_portfolio"] = round(total - pnl, 2)
                risk["growth_window_start_value"] = total
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return risk


def main() -> int:
    if not STATE.exists():
        print(f"missing {STATE}", file=sys.stderr)
        return 1

    if not BACKUP.exists():
        shutil.copy2(STATE, BACKUP)

    lines = STATE.read_text(encoding="utf-8").splitlines()
    cut = None
    for i, line in enumerate(lines):
        if line == "    },":
            cut = i + 1
    if cut is None:
        print("could not find last complete top-level trade", file=sys.stderr)
        return 1

    head_lines = lines[:cut]
    if head_lines and head_lines[-1] == "    },":
        head_lines[-1] = "    }"
    head = "\n".join(head_lines)
    repaired = head + '\n  ],\n  "risk": ' + json.dumps(_default_risk(), indent=2) + "\n}\n"

    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as exc:
        print(f"repaired JSON still invalid: {exc}", file=sys.stderr)
        return 1

    # Refresh balances from the intact header of the corrupt file.
    header_end = head.index('"trades"')
    header = json.loads(head[:header_end].rstrip().rstrip(",") + "\n}")
    data["balances"] = header["balances"]
    data["cost_basis"] = header["cost_basis"]

    STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"repaired {STATE.name}: kept {len(data['trades'])} trades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
