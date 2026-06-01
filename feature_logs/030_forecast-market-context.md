# Feature 030 — ETH/BTC market context in Forecast section

**Status:** complete

## Problem

The auditor report fetches live crypto news but only surfaced it in a standalone
"News headlines" section.  The Forecast section had no visibility into current
market regime — a reader had to scroll past the forecast table to see whether
there was bullish/bearish ETH or BTC news that might explain the forecast.

## Change

`bot/auditor/report.py`:
- Added `_market_context_line(headlines)` helper that picks up to 2 headlines
  tagged with ETH or BTC and formats them as a compact `**Market context:**` line.
- In `render_markdown_report()`, the context line is injected into the `## Forecast`
  section (between the forecast table and the confidence disclaimer) when at least
  one ETH/BTC headline exists.  When no relevant headline exists the line is
  omitted entirely — no output change for setups without news.

Observability only — no decision logic or proposal generation changed.

## Tests added (3 new, in `tests/test_auditor.py`)

- `test_render_markdown_report_forecast_includes_eth_btc_market_context`
- `test_render_markdown_report_forecast_no_context_when_no_eth_btc_headlines`
- `test_render_markdown_report_forecast_no_context_when_no_headlines`

## Verification

```
pytest tests/test_auditor.py -v
# 49 passed
pytest  # 288 passed
```
