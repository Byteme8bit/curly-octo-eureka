# 030 — ETH/BTC market context callout in Forecast section

**Requested:** 2026-06-01 04:00 UTC (automated maintenance cycle)
**Status:** complete

## Request
Wire the same headline summary already used in `bot/auditor/news_client.py` into
`bot/auditor/report.py` so the periodic audit cites 1–2 ETH/BTC headlines next to
the regime read in the Forecast section. Observability only — no decision changes.

## Actions taken
- **`bot/auditor/report.py`**
  - Added `_market_context_callout(headlines, *, max_items=2) -> str`: filters
    the audit's headline list for ETH/BTC tickers, formats up to 2 as a compact
    `_Market context (ETH/BTC):_` block using the existing `_format_news_tag()`
    helper. Returns `""` when no relevant headlines are available.
  - `render_markdown_report()` inserts the callout after the confidence
    disclaimer at the bottom of the `## Forecast` section, before `## News
    headlines`. Pure text addition — no logic changes.
- **`tests/test_auditor.py`**: 3 new tests:
  - `test_market_context_callout_appears_in_forecast_for_eth_btc_headlines`
  - `test_market_context_callout_empty_when_no_eth_btc`
  - `test_render_markdown_report_includes_market_context_in_forecast` —
    asserts the callout is located between the Forecast and News sections.

## Verification
```
python3 -m pytest tests/test_auditor.py -v -k market_context
# Expected: 3 passed
python3 -m pytest --tb=short
# Expected: 288 passed
```

## Notes
- Deliberate choice to place the callout at the *bottom* of Forecast (not next
  to individual bands) so the table formatting is not disrupted.
- The function is only called from `render_markdown_report`; the Discord summary
  (`render_discord_summary`) already shows headlines directly.
