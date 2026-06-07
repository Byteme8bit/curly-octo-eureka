# Feature 040 — feat(observability): triangular arb scan counters

## Status
completed

## Problem
The triangular arbitrage scanner iterated over permutations silently.  No
visibility into how many loops were evaluated per tick, how many were rejected
because a market route was missing, or how many failed the minimum-net-profit
gate.  This made it impossible to distinguish "no good loops exist" from
"the scanner isn't running."

## Fix
Added counters and DEBUG log lines inside `evaluate()`:
- `loops_scanned` — total permutations evaluated (held-asset filter applied)
- `loops_no_market` — loops where `_loop_profit()` returned `None` (missing route)
- `loops_below_min` — loops with a route but net_est ≤ min_net
- A second DEBUG line logs the best loop's path + gross + est_net when an
  intent is emitted.

Pure observability — zero changes to decision logic.

## Files changed
- `bot/strategies/triangular_arbitrage.py` — counters + DEBUG log calls
- `tests/test_triangular_arbitrage.py` — 3 new observability tests (caplog)

## Tests
```
pytest tests/test_triangular_arbitrage.py -v
```
