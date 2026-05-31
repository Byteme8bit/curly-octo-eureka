# 030 — Surface news headlines in auditor report Forecast section

**Requested:** 2026-05-31 (BACKLOG "Now" item)
**Status:** complete

## Request
Wire the headline summary from `scripts/review_news.py` into
`bot/auditor/report.py` so the periodic audit cites 1–2 ETH/BTC headlines
next to the regime read. Observability only — no decision changes.

## Actions taken

### `bot/auditor/report.py`
- Added `_REGIME_TICKERS = frozenset({"ETH", "BTC"})`.
- Added `_select_regime_headlines(headlines, max_items=2)`:
  prefers headlines tagged with ETH or BTC; falls back to the first
  `max_items` headlines when none match.
- `render_markdown_report()` now appends a **"Market context (ETH/BTC
  headlines):"** callout immediately after the Forecast table, using
  `_select_regime_headlines`. The callout is omitted when `headlines` is
  empty (no visual noise on a quiet news day).

### Tests
- `tests/test_auditor.py`: 2 new tests
  - `test_render_markdown_report_market_context_shows_eth_btc_headlines`
  - `test_render_markdown_report_market_context_falls_back_to_any_headline`

## Verification
288 passed. No existing test regressions.
