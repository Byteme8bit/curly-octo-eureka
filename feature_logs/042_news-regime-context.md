# 042 · feat(observability): surface ETH/BTC regime context in auditor report

**Status:** complete

## What changed
### `bot/auditor/report.py`
- Added `_regime_headline_bullets(headlines, max_items=2)` helper: filters
  ETH/BTC-tagged headlines (fallback to first available headline when none
  are tagged) and returns 1–2 bullet strings
- `render_markdown_report()` section 2 "Headline numbers" now appends a
  **Market context (ETH/BTC):** bullet with those 1–2 headlines
  immediately after the circuit-breaker count — so the reader sees market
  regime context next to the PnL numbers
- No change to the "## News headlines" section; no decision logic changes

### `tests/test_auditor.py`
- `test_render_markdown_report_shows_regime_context_for_eth_btc` — asserts
  "Market context" appears in the "Headline numbers" section and an ETH/BTC
  headline title appears in the report
- `test_render_markdown_report_no_regime_context_when_no_headlines` — asserts
  the note is absent when no headlines are available

## Why
The auditor report shows PnL / drawdown numbers but previously had no market
regime context near those numbers. Citing 1–2 ETH/BTC headlines next to the
headline numbers makes it easier to correlate results with what the market
was doing at audit time.

## Verification
```
pytest tests/test_auditor.py -k "regime_context"
```
