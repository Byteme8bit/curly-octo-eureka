# 095 — Paper maker fees + activity watchdog

**Requested:** 2026-08-07 02:11 PDT
**Status:** complete

## Request
PERMISSION GRANTED: paper maker fees + lower slippage. Also automate monitoring/fixes when trades stall — keep real fees/arb, but keep activity up.

## Actions taken
- `PAPER_USE_MAKER_FEES=1` — paper 1-hop preflight uses Kraken **maker** schedule (~0.16%), not fake static understatement; `FEE_FORCE_STATIC` stays **0**
- `SLIPPAGE_BUFFER_PCT=0.0001`
- `config.py` + `bot/engine.py` — `_validate_preflight` / `_paper_preflight_use_maker`
- `scripts/paper_activity_watchdog.py` + systemd timer every **15m**:
  - ensures maker + low slippage
  - never enables `FEE_FORCE_STATIC`
  - never lowers `FEE_RATE` below maker floor
  - if idle ≥45m: nudge z-score toward 1.0, lookback→20, clear adaptive suspend, restart bot
- Deployed to VPS; timer enabled

## Verification
VPS showed **11** paper trades after enable; timer `tradebot-activity-watch.timer` active.
Local: `pytest tests/test_force_multihop_edge.py tests/test_stat_arb.py -q` (agent may leave pending if sandbox-locked).

## Notes
Maker fee on paper is still a real Kraken rate; paper does not post-only so it is optimistic vs pure taker. Triangular still usually blocked on 3× taker math.
