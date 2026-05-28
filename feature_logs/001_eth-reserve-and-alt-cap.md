# 001 — Portfolio constraints: ETH floor and alt allocation cap

**Requested:** 2026-05-25 (early session)
**Status:** complete

## Request
> TradeBot should always keep atleast .25 ETH. No coin aside from ETH or BTC should have more than 40% of portfolio value unless there's a clear reason and market strategy for doing so.

## Actions taken
- **Created `bot/portfolio_constraints.py`** — `PortfolioConstraints` class with:
  - `clamp_eth_sell_size()` — blocks sells that would drop ETH below `MIN_ETH_RESERVE`
  - `validate_intent()` — gates trades, applies size clamps, returns reason on rejection
  - `allows_alt_overweight()` — strategy-backed exception for stat arb / triangular / leader rotation
  - `trim_overweight_intents()` — generates defensive trim intents when alts exceed cap
- **`bot/engine.py`** — wired constraints into the tick before pre-flight validation; prepends trim intents when needed
- **`config.py`** — added `MIN_ETH_RESERVE` (default 0.25) and `MAX_ALT_ALLOCATION_PCT` (default 0.40)
- **`.env`** — added the two settings near `CORE_ASSETS`
- **`.env.example`** — documented under "Portfolio allocation rules"

## Verification
- Modules compile cleanly
- Blocked trades surface in tick output as `ETH reserve — cannot sell below 0.25 ETH` or `Alt cap — XXX would reach NN%`

## Notes
- "Clear reason and market strategy" exception applies to: `require_leader_stable` rotations, `is_expansion` trades, and stat arb / triangular arb signals — all gated by an edge multiplier above the base hurdle.
