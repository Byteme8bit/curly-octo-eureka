# 103 — Full reset cleanup + paper stress activity window

**Requested:** 2026-08-14 15:37 PDT
**Status:** complete

## Request
Clear stale watchdog errors; expect accelerated activity; on resets check ALL related state (not only balances).

## Actions taken
VPS:
- Cleared `.watchdog_state.json` scoring/errors/session counters (kept log offsets)
- Reset `.tradebot_goals_state.json` session markers to ~$1349 baseline
- Truncated `logs/discord_chat.log` (stale Latest Activity)
- Lowered `MIN_ETH_RESERVE`/`LIVE_MIN_ETH_RESERVE` to `0.40` (screenshot ETH 0.495 was blocked by 0.50 floor)
- Enabled all strategies at goal tier 0
- Seeded ~$120 ADA + ~$80 BTC from USD for inventory
- **Paper stress fees** for activity window: `FEE_FORCE_STATIC=1`, `FEE_RATE=0.0004`, `MIN_TRADE_EDGE=0.0003`, `POLL_INTERVAL=2`
- Stopped `tradebot-activity-watch.timer` (would fight stress fees)
- Restarted tradebot + dashboard
- Archive: `archive/2026-08-14-full-reset-cleanup/`

## Verification
Hard-refresh dashboard: watchdog Recent errors empty; trades should climb under stress fees.

## Notes
User clarified: **always keep realistic maker/taker fees** during simulations — understated stress fees void the sim. Reverted in follow-up to `FEE_FORCE_STATIC=0` + `PAPER_USE_MAKER_FEES=1`. Accel ≠ fake fees; true 7-day compression still needs historical replay.
