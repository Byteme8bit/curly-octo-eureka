# 037 — Triangular-arb observability counters

**Requested:** 2026-06-05 (automation cycle)
**Status:** complete

## Request

Add observability counters to `TriangularArbitrageStrategy` so we can tell:
- How many loop permutations were scanned per tick
- How many were rejected and for which reason (no route, missing price, below min net)

Pure observability — no changes to decision logic.

## Actions taken

### `bot/strategies/triangular_arbitrage.py`

- Added `_loop_profit_with_reason()` helper: wraps `_loop_profit()` and returns a
  `(LoopResult | None, str | None)` pair where the string is one of
  `"no_route"`, `"missing_price"`, `"open_loop"`, or `None` (success).
- Replaced the bare loop in `evaluate()` with a call to the new helper;
  increments `loops_scanned` and `reject_counts[reason]` per iteration.
- When the best loop is below `min_net`, `reject_counts["below_min_net"]` is
  also incremented.
- Emits a single `logger.debug("tri-arb scan: …")` line at the end of every
  scan with `loops_scanned`, `best.path`, `best.net_est`, and the full
  `reject_counts` dict.

### `tests/test_triangular_arbitrage.py`

- `test_loop_profit_with_reason_no_route` — reason is `"no_route"` when market has no path.
- `test_loop_profit_with_reason_missing_price` — reason is `"missing_price"` when a symbol is absent.
- `test_loop_profit_with_reason_success` — returns `(LoopResult, None)` on a valid loop.
- `test_debug_log_emitted_on_scan` — DEBUG log contains `"tri-arb scan"` on every evaluate.
- `test_reject_count_below_min_net_logged` — flat prices cause `"below_min_net"` in the log.

## Verification

```
python3 -m pytest tests/test_triangular_arbitrage.py -v
```

Expected: all 8 tests pass (3 original + 5 new).
