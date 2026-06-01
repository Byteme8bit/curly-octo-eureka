# 033 — Triangular arb observability counters

**Requested:** 2026-06-01 (backlog item "Soon")
**Status:** complete

## Request

Add observability counters to `triangular_arbitrage.py`:
how many loops scanned per tick, how many rejected for which reason.
Pure observability — do NOT change the strategy's decision logic.

## Actions taken

- **Modified** `bot/strategies/triangular_arbitrage.py`:
  - Added counters inside `evaluate()`: `n_scanned`, `n_no_path`, `n_below_min`.
  - `n_scanned` increments for every combo that passes the `held` filter.
  - `n_no_path` increments when `_loop_profit()` returns `None` (missing route
    leg or unavailable/zero price — both cases already collapsed to `None` in
    `_loop_profit`).
  - `n_below_min` increments when a valid result is at or below `min_net`.
  - A `logger.debug()` call at the end of the scan loop emits: combos evaluated,
    no-path/zero-price count, below-min count, the threshold value, and the best
    gross profit found.
  - Decision logic (best tracking, intent / opportunity building, blocked list)
    is unchanged.

## Verification

```
python3 -m pytest -v
```

282 tests pass.

## Notes

The debug log fires every tick (throttled by Python's logging level, default
INFO in production). It does not add a new log to the audit trail — only
visible when log level is DEBUG. Future work: expose these counters as Prometheus
or JSONL metrics for external analysis (see "Later" backlog).
