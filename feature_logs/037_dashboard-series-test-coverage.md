# 037 — Test coverage for dashboard series parsers

**Requested:** 2026-06-05 03:02 PDT
**Status:** complete

## Request
Automated test-coverage run: "inspect recent merged code and add missing tests
where coverage is weak and business risk is meaningful." Prioritize new code
paths without tests, edge-case logic, parsing, and shared utilities with large
blast radius.

## Actions taken
- Identified `dashboard/parsers/series.py` (added in #035/#28 "Trader dashboard
  v2") as the weakest-covered recently-merged module: 46% line coverage, all
  pure parsing/aggregation feeding the dashboard charts and forecasts.
- Added deterministic unit tests to `tests/test_dashboard.py`:
  - `_parse_money` — currency/sign/parenthesised-negative/blank/invalid cases.
  - `_parse_confidence` — valid and non-numeric input.
  - `_parse_receipt_time` — ISO with/without tz, date-only, garbage fallback.
  - `build_portfolio_history` — drawdown `%`→fraction conversion and
    consecutive-tick PnL-delta computation, plus the no-logs empty path.
  - `build_trades_series` — per-day bucketing of receipts (counts, net PnL,
    sort order, recent list) and the empty-dir path.

## Verification
- `python3 -m pytest tests/test_dashboard.py` → 32 passed, 3 skipped
  (skips are FastAPI endpoint tests guarded by `pytest.importorskip`).
- `python3 -m pytest -q` → full suite green, no regressions.
- `series.py` line coverage raised 46% → 88%.

## Notes
- No production behavior changed; tests only.
- The 3 skipped tests require `fastapi`, which is not installed in this env;
  pre-existing behavior, unrelated to this change.
