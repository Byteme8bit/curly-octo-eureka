# 088 — Real 0.40% fees + paper baseline reset

**Requested:** 2026-08-06
**Status:** complete

## Request
Stop hallucinated paper gains / fake fees. Reset to real fee model and baseline capital.

## Actions taken
- Archived inflated state → `archive/2026-08-06-real-fees-reset/`
- Reset `.paper_state.json` to `paper_baseline.json` balances; cleared all trades
- Reset `.tradebot_goals_state.json` session markers to ~$1,397.51
- `.env` (local, not committed):
  - `FEE_RATE=0.004`, `FEE_FORCE_STATIC=0` (public Kraken schedule ~0.40%)
  - `MIN_TRADE_EDGE=0.004`, `CRYPTO_MIN_TRADE_EDGE=0.004`
  - `INITIAL_BALANCES` matched baseline
  - `STRATEGIES=cross_momentum,stat_arb` (no triangular)

## Verification
Bot PID running; diagnosis shows `min_trade_edge=0.004`, portfolio ~$1,412, `paper_trades_session=0`, Fee source PUBLIC 0.40%.

## Notes
Prior ~$3.1k paper book was contaminated by optimistic-fee arb fills — discarded, not kept as history.
