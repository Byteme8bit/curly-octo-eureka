# 091 — More arbitrage activity (real fees)

**Requested:** 2026-08-06
**Status:** complete

## Request
Make more arbitrage trades happen; update VPS.

## Actions taken
`.env` (local + VPS), kept `FEE_FORCE_STATIC=0` / real ~0.40% fees:
- `STRATEGIES=cross_momentum,stat_arb,triangular_arbitrage`
- `STAT_ARB_ZSCORE_THRESHOLD=1.6`, lookback 36, more pairs
- `TRADE_COOLDOWN_SECONDS=20`, `IDLE_REEVAL_HOURS=1`
- `MIN_NET_PROFIT_PCT=0.0001` (still `PROFIT_ONLY_MODE=1`)
- Restarted `tradebot.service` on VPS

## Notes
3-leg triangular still needs ~1.2%+ gross to clear real taker fees — rare. Stat-arb mean-reversion is the main activity lever under realistic fees.
