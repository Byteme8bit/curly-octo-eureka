#!/usr/bin/env python3
"""Paper activity watchdog — keep real fees, nudge paper when idle too long.

Safe bounds only:
- Never enables FEE_FORCE_STATIC
- Never lowers fee below MAKER_FEE_RATE
- May enable PAPER_USE_MAKER_FEES, cut slippage, clear adaptive suspend,
  and gently lower STAT_ARB_ZSCORE toward a floor
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("TRADEBOT_ROOT", Path(__file__).resolve().parents[1]))
ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / ".paper_state.json"
DIAG_PATH = ROOT / "logs" / "trade_diagnosis.json"
LOG_PATH = ROOT / "logs" / "paper_activity_watchdog.log"

IDLE_MINUTES = float(os.environ.get("PAPER_ACTIVITY_IDLE_MINUTES", "45"))
Z_FLOOR = float(os.environ.get("PAPER_ACTIVITY_Z_FLOOR", "1.0"))
SLIP_TARGET = float(os.environ.get("PAPER_ACTIVITY_SLIPPAGE", "0.0001"))
MAKER_FLOOR = float(os.environ.get("MAKER_FEE_RATE", "0.0016"))


def _log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _read_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _set_env(text: str, key: str, value: str) -> str:
    if re.search(rf"^{re.escape(key)}=", text, flags=re.M):
        return re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
    return text.rstrip() + f"\n{key}={value}\n"


def _idle_hours(diag: dict, state: dict) -> float:
    adaptive = diag.get("adaptive") or {}
    if adaptive.get("idle_hours") is not None:
        return float(adaptive["idle_hours"])
    risk = state.get("risk") or {}
    last = risk.get("last_trade_at")
    if not last:
        started = risk.get("session_started_at")
        if started:
            try:
                t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
                return max(0.0, (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0)
            except ValueError:
                return 99.0
        return 99.0
    try:
        t0 = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0)
    except ValueError:
        return 99.0


def main() -> int:
    if not ENV_PATH.exists():
        _log("FAIL: missing .env")
        return 1

    env_text = ENV_PATH.read_text(encoding="utf-8")
    env = _read_env(env_text)
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    diag = json.loads(DIAG_PATH.read_text(encoding="utf-8")) if DIAG_PATH.exists() else {}

    # Hard safety: never allow fake static understated fees
    if env.get("FEE_FORCE_STATIC", "0") == "1":
        env_text = _set_env(env_text, "FEE_FORCE_STATIC", "0")
        _log("ACTION: forced FEE_FORCE_STATIC=0 (keep real schedule)")

    fee_rate = float(env.get("FEE_RATE", "0.004") or 0.004)
    if fee_rate < MAKER_FLOOR:
        env_text = _set_env(env_text, "FEE_RATE", f"{MAKER_FLOOR}")
        _log(f"ACTION: raised FEE_RATE to maker floor {MAKER_FLOOR}")

    trades = state.get("trades") or []
    session = int(diag.get("paper_trades_session") or 0)
    idle_h = _idle_hours(diag, state)
    idle_needed = IDLE_MINUTES / 60.0
    _log(
        f"status trades={len(trades)} session={session} idle_h={idle_h:.2f} "
        f"port={diag.get('portfolio_usd')}"
    )

    changed = False
    actions: list[str] = []

    # Always keep maker + low slippage when idle monitoring is on
    if env.get("PAPER_USE_MAKER_FEES", "0") != "1":
        env_text = _set_env(env_text, "PAPER_USE_MAKER_FEES", "1")
        actions.append("PAPER_USE_MAKER_FEES=1")
        changed = True

    slip = float(env.get("SLIPPAGE_BUFFER_PCT", "0.0005") or 0.0005)
    if slip > SLIP_TARGET + 1e-12:
        env_text = _set_env(env_text, "SLIPPAGE_BUFFER_PCT", f"{SLIP_TARGET}")
        actions.append(f"SLIPPAGE_BUFFER_PCT={SLIP_TARGET}")
        changed = True

    dust = float(env.get("DUST_USD", "25") or 25)
    if dust > 5:
        env_text = _set_env(env_text, "DUST_USD", "5")
        actions.append("DUST_USD=5")
        changed = True

    if idle_h >= idle_needed:
        z = float(env.get("STAT_ARB_ZSCORE_THRESHOLD", "1.2") or 1.2)
        if z > Z_FLOOR + 1e-9:
            new_z = max(Z_FLOOR, round(z - 0.05, 2))
            if new_z < z:
                env_text = _set_env(env_text, "STAT_ARB_ZSCORE_THRESHOLD", f"{new_z}")
                actions.append(f"STAT_ARB_ZSCORE_THRESHOLD={new_z}")
                changed = True

        lookback = int(float(env.get("STAT_ARB_LOOKBACK", "24") or 24))
        if lookback > 20:
            env_text = _set_env(env_text, "STAT_ARB_LOOKBACK", "20")
            actions.append("STAT_ARB_LOOKBACK=20")
            changed = True

        risk = dict(state.get("risk") or {})
        if risk.get("adaptive_suspended"):
            risk["adaptive_suspended"] = False
            risk["adaptive_suspended_at"] = None
            risk["adaptive_relax_attempts"] = 0
            state["risk"] = risk
            STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            actions.append("cleared adaptive_suspend")

    if changed:
        ENV_PATH.write_text(env_text, encoding="utf-8")
        _log("ACTION: " + ", ".join(actions))
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", "tradebot.service"],
                check=False,
                timeout=60,
            )
            _log("restarted tradebot.service")
        except Exception as exc:  # noqa: BLE001
            _log(f"WARN restart failed: {exc}")
    else:
        _log("ok — no env changes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
